#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

TODO_RE = re.compile(r"\bTODO:\s*(?P<text>.+?)\s*$")

# If we previously inserted a link/issue marker, ignore it when computing the key.
TRAILING_LINK_RE = re.compile(
    r"\s*(?:\(Issue:\s*https?://[^)]+\)|\(Issue\s*#\d+\)|\(#\d+\)|https?://github\.com/\S+|#\d+)\s*$",
    re.IGNORECASE,
)

OLD_TITLE_RE = re.compile(r"^(?P<text>.+)\s+@\s+(?P<path>[^:]+):(?P<line>\d+)$")


@dataclass(frozen=True)
class Todo:
    path: str
    line: int
    text: str
    key: str

    @property
    def title(self) -> str:
        # Keep titles deterministic and unambiguous (path disambiguates duplicates).
        return f"TODO({self.path}): {self.text}"

    def body(self) -> str:
        return "\n".join(
            [
                "This issue was auto-generated from a TODO in the repository.",
                "",
                f"todo_key: {self.key}",
                f"source: {self.path}:{self.line}",
                "",
                f"TODO: {self.text}",
            ]
        )


def _die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def git_ls_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def normalize_todo_text(raw: str) -> str:
    txt = (raw or "").strip()
    txt = TRAILING_LINK_RE.sub("", txt).strip()
    return txt


def todo_key(path: str, text: str) -> str:
    h = hashlib.sha1(f"{path}:{text}".encode("utf-8"), usedforsecurity=False)
    return h.hexdigest()[:12]


def extract_todos_from_file(path: str) -> list[Todo]:
    todos: list[Todo] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, start=1):
                m = TODO_RE.search(line)
                if not m:
                    continue
                raw = m.group("text")
                text = normalize_todo_text(raw)
                if not text:
                    continue
                todos.append(
                    Todo(path=path, line=i, text=text, key=todo_key(path, text))
                )
    except OSError:
        return []
    return todos


def github_request(
    method: str, url: str, *, token: str, data: Any | None = None
) -> Any:
    body: bytes | None = None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "todo-sync",
        "Authorization": f"Bearer {token}",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read() or b""
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        msg = raw.decode("utf-8", errors="replace") if raw else str(e)
        raise RuntimeError(f"GitHub API {method} {url} failed: {e.code} {msg}") from e


def ensure_label(owner: str, repo: str, *, token: str, name: str) -> None:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        github_request("GET", f"{base}/labels/{urllib.parse.quote(name)}", token=token)
        return
    except Exception:
        pass

    github_request(
        "POST",
        f"{base}/labels",
        token=token,
        data={"name": name, "color": "D4C5F9", "description": "Auto-managed TODO"},
    )


def list_issues(
    owner: str, repo: str, *, token: str, state: str, labels: str
) -> list[dict[str, Any]]:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    per_page = 100
    page = 1
    out: list[dict[str, Any]] = []
    while True:
        url = f"{base}/issues?state={state}&labels={urllib.parse.quote(labels)}&per_page={per_page}&page={page}"
        items_any: Any = github_request("GET", url, token=token)
        if not items_any:
            items: list[dict[str, Any]] = []
        else:
            items_list = items_any if isinstance(items_any, list) else []
            items = [
                cast(dict[str, Any], i)
                for i in items_list
                if isinstance(i, dict) and "pull_request" not in i
            ]
        if not items:
            break
        out.extend(items)
        if len(items) < per_page:
            break
        page += 1
    return out


def issue_key_from_body(body: str) -> str | None:
    m = re.search(r"^todo_key:\s*(?P<key>[0-9a-f]{6,64})\s*$", body or "", re.MULTILINE)
    return m.group("key") if m else None


def close_issue(owner: str, repo: str, *, token: str, number: int) -> None:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    github_request(
        "PATCH", f"{base}/issues/{number}", token=token, data={"state": "closed"}
    )


def create_issue(
    owner: str, repo: str, *, token: str, title: str, body: str, labels: list[str]
) -> dict[str, Any]:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    return github_request(
        "POST",
        f"{base}/issues",
        token=token,
        data={"title": title, "body": body, "labels": labels},
    )


def update_issue(
    owner: str,
    repo: str,
    *,
    token: str,
    number: int,
    body: str | None = None,
    labels: list[str] | None = None,
) -> None:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    payload: dict[str, Any] = {}
    if body is not None:
        payload["body"] = body
    if labels is not None:
        payload["labels"] = labels
    if payload:
        github_request("PATCH", f"{base}/issues/{number}", token=token, data=payload)


def insert_issue_links(
    todos: list[Todo], key_to_issue: dict[str, dict[str, Any]]
) -> int:
    # Map per-file modifications
    by_file: dict[str, list[tuple[int, str]]] = {}

    for t in todos:
        issue = key_to_issue.get(t.key)
        if not issue:
            continue
        url = issue.get("html_url")
        number = issue.get("number")
        if not url or not number:
            continue

        by_file.setdefault(t.path, []).append((t.line, f"Issue: {url}"))

    changed_files = 0
    for path, inserts in by_file.items():
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines(True)
        except OSError:
            continue

        changed = False
        # quick lookup: line -> insert text
        want: dict[int, str] = {ln: ins for (ln, ins) in inserts}

        for idx, line in enumerate(lines, start=1):
            if idx not in want:
                continue
            if "Issue:" in line or "github.com" in line and "/issues/" in line:
                continue

            # Only touch lines that still contain TODO:
            if "TODO:" not in line:
                continue

            new_line = line.rstrip("\n") + f" ({want[idx]})\n"
            lines[idx - 1] = new_line
            changed = True

        if changed:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                changed_files += 1
            except OSError:
                continue

    return changed_files


def main() -> int:
    repo_full = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not repo_full or "/" not in repo_full:
        _die("GITHUB_REPOSITORY not set (expected owner/repo)")
    if not token:
        _die("GITHUB_TOKEN not set")

    owner, repo = repo_full.split("/", 1)

    # Only scan tracked files (avoids .venv noise and random vendor TODOs).
    # Also exclude this tooling folder so we don't generate issues from the sync script itself.
    todos: list[Todo] = []
    for path in git_ls_files():
        if path.startswith(".github/scripts/"):
            continue
        todos.extend(extract_todos_from_file(path))

    ensure_label(owner, repo, token=token, name="todo")

    existing = list_issues(owner, repo, token=token, state="all", labels="todo")

    # Build lookup tables for existing issues.
    existing_by_key: dict[str, dict[str, Any]] = {}
    existing_by_title: dict[str, dict[str, Any]] = {}

    for issue in existing:
        title = str(issue.get("title") or "")
        body = str(issue.get("body") or "")
        existing_by_title[title] = issue
        k = issue_key_from_body(body)
        if k:
            existing_by_key[k] = issue

    # Create/adopt issues for current TODOs.
    key_to_issue: dict[str, dict[str, Any]] = {}
    for t in todos:
        issue = existing_by_key.get(t.key)
        if issue is None:
            # Adopt an existing issue by title if it matches.
            issue = existing_by_title.get(t.title)
            if issue is not None:
                body = str(issue.get("body") or "")
                if not issue_key_from_body(body):
                    update_issue(
                        owner,
                        repo,
                        token=token,
                        number=int(issue["number"]),
                        body=body + "\n\n" + f"todo_key: {t.key}\n",
                    )
            else:
                issue = create_issue(
                    owner,
                    repo,
                    token=token,
                    title=t.title,
                    body=t.body(),
                    labels=["todo"],
                )

        key_to_issue[t.key] = issue

    # Close stale issues (two strategies):
    # 1) Issues with todo_key that no longer exist.
    current_keys = {t.key for t in todos}
    for k, issue in existing_by_key.items():
        if k in current_keys:
            continue
        if str(issue.get("state")) == "open":
            close_issue(owner, repo, token=token, number=int(issue["number"]))

    # 2) Migrate/close old-format titles: "<text> @ <path>:<line>"
    current_pairs = {(t.path, t.text) for t in todos}
    for issue in existing:
        if str(issue.get("state")) != "open":
            continue
        title = str(issue.get("title") or "")
        if issue_key_from_body(str(issue.get("body") or "")):
            continue

        m = OLD_TITLE_RE.match(title)
        if not m:
            continue
        text = normalize_todo_text(m.group("text"))
        path = m.group("path")
        if (path, text) not in current_pairs:
            close_issue(owner, repo, token=token, number=int(issue["number"]))

    changed_files = insert_issue_links(todos, key_to_issue)
    print(f"Synced {len(todos)} TODO(s); updated {changed_files} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
