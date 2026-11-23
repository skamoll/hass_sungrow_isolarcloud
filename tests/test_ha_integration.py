"""End-to-end Home Assistant Core integration test (runs when homeassistant is installed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

if importlib.util.find_spec("homeassistant") is None:
    pytest.skip("homeassistant package not installed", allow_module_level=True)

from homeassistant import bootstrap, loader
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from py_sungrow_isolarcloud.models import (
    DevicePoint,
    DeviceSummary,
    PlantData,
    PlantFlow,
    PlantSummary,
    ValueUnit,
)

from custom_components.hass_sungrow_isolarcloud.const import (
    CONF_GATEWAY,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)


def _sample_plant_data() -> dict[str, PlantData]:
    return {
        "1234567": PlantData(
            summary=PlantSummary(
                ps_id="1234567",
                ps_name="Casa",
                ps_status=1,
                design_capacity_kwp=6.0,
            ),
            flow=PlantFlow(
                pv_power=ValueUnit(2.45, "kW"),
                load_power=ValueUnit(1.10, "kW"),
                grid_power=ValueUnit(-1.35, "kW"),
                battery_power=ValueUnit(0.0, "kW"),
                battery_soc=88.0,
                daily_pv_energy=ValueUnit(14.2, "kWh"),
                total_pv_energy=ValueUnit(4863.0, "kWh"),
                last_update_time="2026-11-23 00:30:00",
            ),
            devices=[
                DeviceSummary(
                    ps_id="1234567",
                    ps_key="1234567_14_1_1",
                    uuid="8633308",
                    device_name="Inverter SH6.0RS",
                    device_model="SH6.0RS",
                    device_sn="SN123456",
                    device_type=14,
                    dev_status=1,
                    fault_status="4",
                    points={
                        58603: DevicePoint(
                            point_id=58603,
                            name="Internal temperature",
                            value=24.5,
                            unit="°C",
                            is_numeric=True,
                        )
                    },
                )
            ],
        )
    }


@pytest.mark.asyncio
async def test_ha_setup_devices_entities_and_unload(tmp_path: Path) -> None:
    """Verify full setup, device hierarchy, entities, and unload on real HA Core."""
    (tmp_path / "custom_components").symlink_to(
        Path(__file__).resolve().parent.parent / "custom_components"
    )
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    await bootstrap.async_from_config_dict({}, hass)
    await hass.async_start()
    try:
        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="iSolarCloud (test@example.com)",
            data={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "secret",
                CONF_GATEWAY: "eu",
            },
            options={CONF_SCAN_INTERVAL: 120},
            source="user",
            unique_id="999:test@example.com",
            discovery_keys={},
            subentries_data=None,
        )
        with patch(
            "py_sungrow_isolarcloud.client.ISolarCloudClient.async_fetch_all_plants",
            new=AsyncMock(return_value=_sample_plant_data()),
        ):
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED

        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        assert len(devices) == 2

        plant_dev = dev_reg.async_get_device(identifiers={(DOMAIN, "plant_1234567")})
        child_dev = dev_reg.async_get_device(identifiers={(DOMAIN, "device_1234567_14_1_1")})
        assert plant_dev is not None
        assert plant_dev.name == "PV 1234567"
        assert child_dev is not None
        assert child_dev.via_device_id == plant_dev.id

        ent_reg = er.async_get(hass)
        entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        assert len(entities) == 26
        assert not any(e.entity_id.endswith("_2") for e in entities)

        export_state = hass.states.get("sensor.pv_1234567_grid_export_power")
        assert export_state is not None
        assert export_state.state == "1.35"

        status_state = hass.states.get("sensor.pv_1234567_plant_status")
        assert status_state is not None
        assert status_state.state == "Normal"

        refresh_btn = hass.states.get("button.pv_1234567_refresh_data")
        assert refresh_btn is not None

        last_update_state = hass.states.get("sensor.pv_1234567_last_update")
        assert last_update_state is not None
        assert last_update_state.state not in ("unknown", "unavailable")

        pv_state = hass.states.get("sensor.pv_1234567_pv_power")
        assert pv_state is not None
        assert pv_state.state == "2.45"
        assert pv_state.attributes["unit_of_measurement"] == "kW"

        soc_state = hass.states.get("sensor.pv_1234567_battery_soc")
        assert soc_state is not None
        assert soc_state.state == "88.0"

        online_state = hass.states.get("binary_sensor.pv_1234567_online")
        assert online_state is not None
        assert online_state.state == "on"

        from custom_components.hass_sungrow_isolarcloud.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry"]["data"]["username"] == "**REDACTED**"
        assert diag["entry"]["data"]["password"] == "**REDACTED**"
        assert diag["plants"]["1234567"]["devices"][0]["point_count"] == 1

        with patch(
            "py_sungrow_isolarcloud.client.ISolarCloudClient.async_fetch_all_plants",
            new=AsyncMock(return_value=_sample_plant_data()),
        ):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.pv_1234567_refresh_data"},
                blocking=True,
            )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
    finally:
        await hass.async_stop()


@pytest.mark.asyncio
async def test_offline_notification_and_recovery(tmp_path: Path) -> None:
    """Verify persistent notification on offline threshold and dismissal on recovery."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    (tmp_path / "custom_components").symlink_to(
        Path(__file__).resolve().parent.parent / "custom_components"
    )
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    await bootstrap.async_from_config_dict({}, hass)
    await hass.async_start()
    try:
        offline_data = _sample_plant_data()
        offline_data["1234567"].summary.ps_status = 0

        entry = ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title="iSolarCloud (test@example.com)",
            data={
                CONF_USERNAME: "test@example.com",
                CONF_PASSWORD: "secret",
                CONF_GATEWAY: "eu",
            },
            options={
                CONF_SCAN_INTERVAL: 120,
                "offline_notify_enabled": True,
                "offline_threshold_minutes": 10,
                "notify_service": "",
            },
            source="user",
            unique_id="999:test@example.com",
            discovery_keys={},
            subentries_data=None,
        )
        with patch(
            "py_sungrow_isolarcloud.client.ISolarCloudClient.async_fetch_all_plants",
            new=AsyncMock(return_value=offline_data),
        ):
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert "1234567" in coordinator._offline_since
        assert "1234567" not in coordinator._notified_offline

        # Simulate elapsed offline period past the 10-minute threshold
        coordinator._offline_since["1234567"] = dt_util.utcnow() - timedelta(minutes=11)
        with patch(
            "py_sungrow_isolarcloud.client.ISolarCloudClient.async_fetch_all_plants",
            new=AsyncMock(return_value=offline_data),
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert "1234567" in coordinator._notified_offline
        assert hass.states.get(f"persistent_notification.{DOMAIN}_offline_1234567") is not None

        # Simulate recovery
        online_data = _sample_plant_data()
        with patch(
            "py_sungrow_isolarcloud.client.ISolarCloudClient.async_fetch_all_plants",
            new=AsyncMock(return_value=online_data),
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert "1234567" not in coordinator._offline_since
        assert "1234567" not in coordinator._notified_offline
        assert hass.states.get(f"persistent_notification.{DOMAIN}_offline_1234567") is None
    finally:
        await hass.async_stop()
