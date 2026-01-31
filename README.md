
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![GH Release](https://img.shields.io/github/v/release/roblandry/apex-neptune-home-assistant?sort=semver)](https://github.com/roblandry/apex-neptune-home-assistant/releases)
[![GH Last Commit](https://img.shields.io/github/last-commit/roblandry/apex-neptune-home-assistant?logo=github)](https://github.com/roblandry/apex-neptune-home-assistant/commits/main)
[![Codecov](https://codecov.io/gh/roblandry/apex-neptune-home-assistant/branch/main/graph/badge.svg)](https://codecov.io/gh/roblandry/apex-neptune-home-assistant)
[![GitHub Clones](https://img.shields.io/badge/dynamic/json?color=success&label=Clone&query=count&url=https://gist.githubusercontent.com/roblandry/90aeef6ae32b7dd94f74f067de2277fb/raw/clone.json&logo=github)](https://github.com/MShawon/github-clone-count-badge)
![GH Code Size](https://img.shields.io/github/languages/code-size/roblandry/apex-neptune-home-assistant)
[![BuyMeCoffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-donate-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/roblandry)

# Apex Fusion (Local)

> [!CAUTION]
> This is a Work In Progress and is subject to changes

Home Assistant custom integration for local (LAN) polling of an Apex controller.

## Features

- REST-first polling with legacy (CGI) fallback
- Entities for common Apex/EB832 outlets and sensors
- Config flow (UI setup)
- Designed for stable device identity and robust backoff on rate limiting

## Installation

### HACS (Custom Repository)

> [!CAUTION]
> This is a Work In Progress and is subject to changes. It will be added to HACS once complete.

<del>

1. HACS → Integrations → 3-dot menu → **Custom repositories**
2. Add this repository URL as **Integration**
3. Install **Apex Fusion (Local)**
4. Restart Home Assistant

</del>

### Manual

Copy `custom_components/apex_fusion` into your Home Assistant `config/custom_components/apex_fusion` folder, then restart Home Assistant.

## Configuration

Add the integration from Home Assistant UI:

1. Settings → Devices & services → Add integration
2. Search for **Apex Fusion (Local)**

## Development

- Create and use `.venv`
- Run tests: `.venv/bin/pytest -q`
- Lint: `.venv/bin/ruff check .`

## License

MIT. See [LICENSE](LICENSE).
