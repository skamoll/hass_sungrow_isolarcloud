# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] - 2026-11-23

### Changed
- Changed default polling interval (`DEFAULT_SCAN_INTERVAL`) from `120s` to `300s` (5 minutes) to match iSolarCloud logger cadence and reduce unnecessary API traffic.
- Added progressive retry backoff ladder (`30s → 90s → 180s → 300s`, floored at base interval) on transient coordinator failures with automatic schedule restoration upon recovery.

## [0.1.3] - 2026-11-23

### Fixed
- Bumped `py-sungrow-isolarcloud` requirement to `0.1.1` to fix inverted `battery_charge_power` / `battery_discharge_power` signs (`-` = charging, `+` = discharging).

## [0.1.2] - 2026-11-23

### Added
- Structured debug logging across setup, coordinator polling cycles, device registration, options updates, and config/reauth flows (without exposing secrets).
- Hardened coordinator error handling (`ConfigEntryAuthFailed`, `UpdateFailed`, unexpected exception capture, consecutive error counter, and recovery logging) plus UI `reauth_confirm` flow.
- Configurable plant offline notifications (`offline_notify_enabled`, `offline_threshold_minutes` default `15`, optional `notify_service`) creating persistent notifications (and optional `notify.*` push alerts) and auto-dismissing upon recovery.

## [0.1.1] - 2026-11-23

### Changed
- Plant device names and entity prefixes now use the unique numeric `ps_id` (`PV <ps_id>` / `sensor.pv_<ps_id>_*`) instead of the owner's plant name.
- Added `"categories": ["energy"]` to `manifest.json` and `workflow_dispatch` to CI.

## [0.1.0] - 2026-11-23

### Added
- Native Home Assistant custom integration (`custom_components/hass_sungrow_isolarcloud`) consuming `py-sungrow-isolarcloud==0.1.0`.
- `ConfigFlow`, `OptionsFlow`, and `Reauth` UI setup with regional gateway selection (`auto` + 6 regions) and configurable polling interval (`30s`–`600s`, default `120s`).
- Plant device (`PV <plant>`) with canonical `kW`/`kWh` flow/energy sensors, directional import/export & charge/discharge power sensors, self-consumption, monthly PV, monetary income, CO2 reduced, local weather temperature, and diagnostic `Refresh data` button.
- Dynamic child device entities linked via `via_device_id` (`via_device` fallback on HA `<2026.8`), automatic `EntityCategory.DIAGNOSTIC` classification, and on-demand active fault attributes on `binary_sensor.*_fault`.
- Bilingual UI (`en` / `es`) with deterministic English `entity_id`s and automatic iSolarCloud API `lang` mapping for device telemetry points.
- Standard `diagnostics.py` redacting credentials, tokens, user IDs, and serial numbers.
- Preconfigured Lovelace `Power Flow Card Plus` example (`examples/power-flow-card-plus.yaml`) and Energy Dashboard setup guide.
