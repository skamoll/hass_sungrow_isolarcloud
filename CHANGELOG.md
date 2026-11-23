# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-23

### Added
- Native Home Assistant custom integration (`custom_components/hass_sungrow_isolarcloud`) consuming `py-sungrow-isolarcloud==0.1.0`.
- `ConfigFlow`, `OptionsFlow`, and `Reauth` UI setup with regional gateway selection (`auto` + 6 regions) and configurable polling interval (`30s`–`600s`, default `120s`).
- Plant device (`PV <plant>`) with canonical `kW`/`kWh` flow/energy sensors, directional import/export & charge/discharge power sensors, self-consumption, monthly PV, monetary income, CO2 reduced, local weather temperature, and diagnostic `Refresh data` button.
- Dynamic child device entities linked via `via_device_id` (`via_device` fallback on HA `<2026.8`), automatic `EntityCategory.DIAGNOSTIC` classification, and on-demand active fault attributes on `binary_sensor.*_fault`.
- Bilingual UI (`en` / `es`) with deterministic English `entity_id`s and automatic iSolarCloud API `lang` mapping for device telemetry points.
- Standard `diagnostics.py` redacting credentials, tokens, user IDs, and serial numbers.
- Preconfigured Lovelace `Power Flow Card Plus` example (`examples/power-flow-card-plus.yaml`) and Energy Dashboard setup guide.
