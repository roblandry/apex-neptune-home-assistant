"""Tests for Apex Fusion switch platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast
from unittest.mock import AsyncMock

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apex_fusion.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)


@dataclass
class _CoordinatorStub:
    data: dict[str, Any]
    last_update_success: bool = True
    device_identifier: str = "TEST"
    async_request_refresh: AsyncMock = AsyncMock()

    def async_add_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        def _unsub() -> None:
            return None

        return _unsub


def test_switch_helpers_cover_all_branches():
    from custom_components.apex_fusion import switch

    assert switch._pretty_model("Nero5") == "Nero 5"
    assert switch._pretty_model("Nero") == "Nero"
    assert switch._pretty_model("123") == "123"
    assert switch._pretty_model("A1B") == "A1B"
    assert switch._pretty_model("") == ""

    assert (
        switch._friendly_outlet_name(
            outlet_name="Nero_5_F", outlet_type="MXMPump|AI|Nero5"
        )
        == "AI Nero 5 (Nero 5 F)"
    )
    assert (
        switch._friendly_outlet_name(
            outlet_name="Nero_5", outlet_type="MXMPump|AI|Nero5"
        )
        == "AI Nero 5"
    )
    assert (
        switch._friendly_outlet_name(outlet_name="Heater_1", outlet_type=None)
        == "Heater 1"
    )
    assert switch._friendly_outlet_name(outlet_name="", outlet_type="x") == ""

    assert switch._is_switchable_outlet({"state": "AON"}) is True
    assert switch._is_switchable_outlet({"state": "TBL"}) is True
    assert switch._is_switchable_outlet({"state": "XXX"}) is False

    assert switch._is_auto_state("AON") is True
    assert switch._is_auto_state("AOF") is True
    assert switch._is_auto_state("TBL") is True
    assert switch._is_auto_state("ON") is False

    assert switch._is_energized_state("AON") is True
    assert switch._is_energized_state("ON") is True
    assert switch._is_energized_state("TBL") is True
    assert switch._is_energized_state("AOF") is False


async def test_switch_setup_creates_outlet_auto_and_state_switches(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.2.3.4", CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id="1.2.3.4",
        title="Apex (1.2.3.4)",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [
                "not-a-dict",
                {"name": "MissingDid", "state": "AON", "type": "EB832"},
                {
                    "name": "Outlet_1",
                    "device_id": "O1",
                    "state": "AON",
                    "type": "EB832",
                },
                {"name": "Ignored", "device_id": "OX", "state": "XXX", "type": "EB832"},
                {"name": "Bad", "device_id": "O2", "state": "TBL", "type": "EB832"},
                {"name": "MXM", "device_id": "O3", "state": "AON", "type": "MXMPump"},
            ],
        },
        last_update_success=True,
        device_identifier="ABC",
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    added: list[Any] = []

    def _add_entities(new_entities, update_before_add: bool = False):
        added.extend(list(new_entities))

    from custom_components.apex_fusion import switch

    await switch.async_setup_entry(hass, cast(Any, entry), _add_entities)

    # O1/O2/O3 are switchable -> each yields Auto + State
    assert len(added) == 6

    for ent in added:
        ent.async_write_ha_state = lambda *args, **kwargs: None
        await ent.async_added_to_hass()
        ent._handle_coordinator_update()
        await ent.async_will_remove_from_hass()


async def test_switch_find_outlet_handles_non_list_and_non_dict(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.2.3.4", CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id="1.2.3.4",
        title="Apex (1.2.3.4)",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={"meta": {"serial": "ABC"}, "outlets": "nope"},
        device_identifier="ABC",
    )
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )
    assert ent._find_outlet() == {}
    assert ent._read_is_on() is False

    coordinator.data = {
        "meta": {"serial": "ABC"},
        "outlets": [
            "not-a-dict",
            {"device_id": "O1", "state": "AON"},
        ],
    }
    assert ent._find_outlet().get("device_id") == "O1"

    # No matching did -> return {} (covers end-of-loop return).
    ent2 = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="NO_MATCH", name="X"),
    )
    assert ent2._find_outlet() == {}


def test_switch_build_base_url_strips_slash():
    from custom_components.apex_fusion.coordinator import build_base_url

    assert build_base_url("http://1.2.3.4/") == "http://1.2.3.4"
    assert build_base_url("1.2.3.4/") == "http://1.2.3.4"


async def test_switch_extra_attrs_mxm_non_dict_entry(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.2.3.4", CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id="1.2.3.4",
        title="Apex (1.2.3.4)",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "name": "Outlet_1", "state": "OFF"}],
            "mxm_devices": {"Outlet_1": "not-a-dict"},
        }
    )
    coordinator.device_identifier = "ABC"
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )
    # Should not crash and should not add mxm_* keys.
    attrs = ent._read_extra_attrs()
    assert "mxm_rev" not in attrs


async def test_switch_control_put_raises_timeout_and_client_error(
    hass, enable_custom_integrations
):
    """Hit the PUT exception branches."""
    import asyncio

    import aiohttp

    class _Resp:
        def __init__(self, status: int, text: str):
            self.status = status
            self._text = text
            self.headers = {}

        async def text(self) -> str:
            return self._text

        def raise_for_status(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Session:
        def __init__(self):
            self._put_calls = 0
            self.cookie_jar = type(
                "_Jar",
                (),
                {
                    "filter_cookies": lambda *_a, **_k: {},
                    "update_cookies": lambda *_a, **_k: None,
                },
            )()

        def post(self, *args, **kwargs):
            # Valid login with sid
            return _Resp(200, '{"connect.sid": "abc"}')

        def put(self, *args, **kwargs):
            self._put_calls += 1
            if self._put_calls == 1:
                raise asyncio.TimeoutError()
            raise aiohttp.ClientError("boom")

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"
    coordinator.async_request_refresh = AsyncMock(return_value=None)

    from custom_components.apex_fusion import switch as switch_mod
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    session = _Session()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)

        with pytest.raises(HomeAssistantError):
            await ent.async_turn_on()

        with pytest.raises(HomeAssistantError):
            await ent.async_turn_on()


async def test_switch_control_requires_password(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "1.2.3.4", CONF_USERNAME: "admin", CONF_PASSWORD: ""},
        unique_id="1.2.3.4",
        title="Apex (1.2.3.4)",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    with pytest.raises(HomeAssistantError):
        await ent.async_turn_on()


async def test_switch_control_rest_success(
    hass, aioclient_mock, enable_custom_integrations
):
    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"
    coordinator.async_request_refresh = AsyncMock(return_value=None)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    aioclient_mock.post(
        f"http://{host}/rest/login",
        status=200,
        text='{"connect.sid": "abc"}',
    )
    aioclient_mock.put(
        f"http://{host}/rest/status/outputs/O1",
        status=200,
        text="{}",
    )

    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )
    await ent.async_turn_on()
    coordinator.async_request_refresh.assert_awaited()


async def test_switch_control_rest_success_without_sid(
    hass, aioclient_mock, enable_custom_integrations
):
    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"
    coordinator.async_request_refresh = AsyncMock(return_value=None)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Login returns no connect.sid -> should still attempt PUT without Cookie.
    aioclient_mock.post(
        f"http://{host}/rest/login",
        status=200,
        text="{}",
    )
    aioclient_mock.put(
        f"http://{host}/rest/status/outputs/O1",
        status=200,
        text="{}",
    )

    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )
    await ent.async_turn_on()


async def test_switch_control_rest_error_branches(hass, enable_custom_integrations):
    """Cover the REST error branches without relying on aioclient_mock behavior."""

    class _Resp:
        def __init__(self, status: int, text: str):
            self.status = status
            self._text = text
            self.headers = {}

        async def text(self) -> str:
            return self._text

        def raise_for_status(self) -> None:
            if self.status >= 400:
                raise aiohttp.ClientResponseError(
                    request_info=cast(Any, None),
                    history=(),
                    status=self.status,
                    message="err",
                    headers=cast(Any, {}),
                )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Session:
        def __init__(self):
            self._step = 0
            self.cookie_jar = type(
                "_Jar",
                (),
                {
                    "filter_cookies": lambda *_a, **_k: {},
                    "update_cookies": lambda *_a, **_k: None,
                },
            )()

        def post(self, *args, **kwargs):
            self._step += 1
            # First: 404 not supported
            if self._step == 1:
                return _Resp(404, "{}")
            # Second: 401 invalid auth
            if self._step == 2:
                return _Resp(401, "{}")
            # Third: invalid JSON triggers decode error
            return _Resp(200, "not-json")

        def put(self, *args, **kwargs):
            return _Resp(401, "{}")

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"
    coordinator.async_request_refresh = AsyncMock(return_value=None)

    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    from custom_components.apex_fusion import switch as switch_mod

    session = _Session()

    # 404 not supported
    with pytest.raises(HomeAssistantError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
            await ent.async_turn_on()

    # 401 invalid
    with pytest.raises(HomeAssistantError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
            await ent.async_turn_on()

    # JSON decode error
    with pytest.raises(HomeAssistantError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
            await ent.async_turn_on()

    # Successful login but PUT unauthorized
    class _Session2(_Session):
        def post(self, *args, **kwargs):
            return _Resp(200, '{"connect.sid": "abc"}')

    session2 = _Session2()
    with pytest.raises(HomeAssistantError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session2)
            await ent.async_turn_on()


async def test_switch_control_invalid_mode_raises(hass, enable_custom_integrations):
    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"

    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    with pytest.raises(HomeAssistantError):
        await ent._async_set_mode("BAD")


async def test_switch_control_uses_cookie_jar_sid_no_login(
    hass, enable_custom_integrations
):
    class _NullTimeout:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Resp:
        def __init__(self, status: int):
            self.status = status
            self.headers: dict[str, str] = {}

        async def text(self) -> str:
            return "{}"

        def raise_for_status(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _CookieMorsel:
        def __init__(self, value: str):
            self.value = value

    class _Jar:
        def filter_cookies(self, *_a, **_k):
            return {"connect.sid": _CookieMorsel("abc")}

    class _Session:
        def __init__(self):
            self.cookie_jar = _Jar()
            self.post_calls = 0
            self.put_calls = 0

        def post(self, *args, **kwargs):
            self.post_calls += 1
            return _Resp(200)

        def put(self, *args, **kwargs):
            self.put_calls += 1
            return _Resp(200)

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"
    coordinator.async_request_refresh = AsyncMock(return_value=None)

    from custom_components.apex_fusion import switch as switch_mod
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    session = _Session()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
        mp.setattr(switch_mod.async_timeout, "timeout", lambda _t: _NullTimeout())
        await ent.async_turn_on()

    assert session.post_calls == 0
    assert session.put_calls == 1


async def test_switch_control_429_login_calls_coordinator_backoff(
    hass, enable_custom_integrations
):
    class _NullTimeout:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Resp:
        def __init__(self, status: int, *, headers: dict[str, str] | None = None):
            self.status = status
            self.headers = headers or {}

        async def text(self) -> str:
            return "{}"

        def raise_for_status(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Jar:
        def filter_cookies(self, *_a, **_k):
            return {}

        def update_cookies(self, *_a, **_k):
            return None

    class _Session:
        def __init__(self):
            self.cookie_jar = _Jar()

        def post(self, *args, **kwargs):
            return _Resp(429, headers={"Retry-After": "2"})

        def put(self, *args, **kwargs):
            raise AssertionError("PUT should not be called when login is rate limited")

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    backoff: dict[str, Any] = {}

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )

    def _disable_rest(*, seconds: float, reason: str) -> None:
        backoff["seconds"] = seconds
        backoff["reason"] = reason

    coordinator.device_identifier = "ABC"
    coordinator._disable_rest = _disable_rest  # type: ignore[attr-defined]

    from custom_components.apex_fusion import switch as switch_mod
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    session = _Session()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
        mp.setattr(switch_mod.async_timeout, "timeout", lambda _t: _NullTimeout())
        with pytest.raises(HomeAssistantError):
            await ent.async_turn_on()

    assert backoff["seconds"] == 2.0
    assert backoff["reason"] == "rate_limited_control"


async def test_switch_control_429_login_blank_retry_after_defaults_to_300(
    hass, enable_custom_integrations
):
    class _NullTimeout:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Resp:
        def __init__(self, status: int, *, headers: dict[str, str] | None = None):
            self.status = status
            self.headers = headers or {}

        async def text(self) -> str:
            return "{}"

        def raise_for_status(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Jar:
        def filter_cookies(self, *_a, **_k):
            return {}

        def update_cookies(self, *_a, **_k):
            return None

    class _Session:
        def __init__(self):
            self.cookie_jar = _Jar()

        def post(self, *args, **kwargs):
            # Blank Retry-After exercises the "if not t" branch.
            return _Resp(429, headers={"Retry-After": " "})

        def put(self, *args, **kwargs):
            raise AssertionError("PUT should not be called")

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "not-admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    backoff: dict[str, Any] = {}

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )

    def _disable_rest(*, seconds: float, reason: str) -> None:
        backoff["seconds"] = seconds
        backoff["reason"] = reason

    coordinator.device_identifier = "ABC"
    coordinator._disable_rest = _disable_rest  # type: ignore[attr-defined]

    from custom_components.apex_fusion import switch as switch_mod
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    session = _Session()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
        mp.setattr(switch_mod.async_timeout, "timeout", lambda _t: _NullTimeout())
        with pytest.raises(HomeAssistantError):
            await ent.async_turn_on()

    assert backoff["seconds"] == 300.0
    assert backoff["reason"] == "rate_limited_control"


async def test_switch_control_429_login_handles_bad_headers_and_backoff_errors(
    hass, enable_custom_integrations
):
    """Covers retry-after exception branch and _note_rate_limited exception swallowing."""

    class _NullTimeout:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Resp:
        def __init__(self, status: int):
            self.status = status
            self.headers = None  # type: ignore[assignment]

        async def text(self) -> str:
            return "{}"

        def raise_for_status(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Jar:
        def filter_cookies(self, *_a, **_k):
            return {}

        def update_cookies(self, *_a, **_k):
            return None

    class _Session:
        def __init__(self):
            self.cookie_jar = _Jar()

        def post(self, *args, **kwargs):
            return _Resp(429)

        def put(self, *args, **kwargs):
            raise AssertionError("PUT should not be called")

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "not-admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )
    coordinator.device_identifier = "ABC"

    def _disable_rest(*, seconds: float, reason: str) -> None:
        raise RuntimeError("boom")

    coordinator._disable_rest = _disable_rest  # type: ignore[attr-defined]

    from custom_components.apex_fusion import switch as switch_mod
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    session = _Session()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
        mp.setattr(switch_mod.async_timeout, "timeout", lambda _t: _NullTimeout())
        with pytest.raises(HomeAssistantError):
            await ent.async_turn_on()


async def test_switch_control_429_put_calls_coordinator_backoff_default(
    hass, enable_custom_integrations
):
    class _NullTimeout:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Resp:
        def __init__(
            self, status: int, body: str, *, headers: dict[str, str] | None = None
        ):
            self.status = status
            self._body = body
            self.headers = headers or {}

        async def text(self) -> str:
            return self._body

        def raise_for_status(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Jar:
        def filter_cookies(self, *_a, **_k):
            return {}

        def update_cookies(self, *_a, **_k):
            return None

    class _Session:
        def __init__(self):
            self.cookie_jar = _Jar()
            self._put_called = False

        def post(self, *args, **kwargs):
            return _Resp(200, '{"connect.sid": "abc"}')

        def put(self, *args, **kwargs):
            self._put_called = True
            return _Resp(429, "{}")

    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    backoff: dict[str, Any] = {}

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "OFF"}],
        }
    )

    def _disable_rest(*, seconds: float, reason: str) -> None:
        backoff["seconds"] = seconds
        backoff["reason"] = reason

    coordinator.device_identifier = "ABC"
    coordinator._disable_rest = _disable_rest  # type: ignore[attr-defined]

    from custom_components.apex_fusion import switch as switch_mod
    from custom_components.apex_fusion.switch import ApexOutletStateSwitch, _OutletRef

    ent = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="O1"),
    )

    session = _Session()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(switch_mod, "async_get_clientsession", lambda _hass: session)
        mp.setattr(switch_mod.async_timeout, "timeout", lambda _t: _NullTimeout())
        with pytest.raises(HomeAssistantError):
            await ent.async_turn_on()

    assert session._put_called is True
    assert backoff["seconds"] == 300.0
    assert backoff["reason"] == "rate_limited_control"


async def test_outlet_switch_turn_methods_call_expected_modes(
    hass, enable_custom_integrations
):
    host = "1.2.3.4"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: host, CONF_USERNAME: "admin", CONF_PASSWORD: "pw"},
        unique_id=host,
        title=f"Apex ({host})",
    )
    entry.add_to_hass(hass)

    coordinator = _CoordinatorStub(
        data={
            "meta": {"serial": "ABC"},
            "outlets": [{"device_id": "O1", "state": "AON"}],
        },
        device_identifier="ABC",
    )

    from custom_components.apex_fusion.switch import (
        ApexOutletAutoSwitch,
        ApexOutletStateSwitch,
        _OutletRef,
    )

    auto = ApexOutletAutoSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="Outlet"),
    )
    state = ApexOutletStateSwitch(
        hass,
        cast(Any, coordinator),
        cast(Any, entry),
        ref=_OutletRef(did="O1", name="Outlet"),
    )

    auto._async_set_mode = AsyncMock()  # type: ignore[method-assign]
    state._async_set_mode = AsyncMock()  # type: ignore[method-assign]

    await auto.async_turn_on()
    auto._async_set_mode.assert_awaited_with("AUTO")

    auto._async_set_mode.reset_mock()
    await auto.async_turn_off()
    auto._async_set_mode.assert_awaited_with("ON")

    # Not energized -> should turn OFF when leaving AUTO.
    coordinator.data["outlets"][0]["state"] = "AOF"
    auto._async_set_mode.reset_mock()
    await auto.async_turn_off()
    auto._async_set_mode.assert_awaited_with("OFF")

    await state.async_turn_on()
    state._async_set_mode.assert_awaited_with("ON")
    state._async_set_mode.reset_mock()
    await state.async_turn_off()
    state._async_set_mode.assert_awaited_with("OFF")
