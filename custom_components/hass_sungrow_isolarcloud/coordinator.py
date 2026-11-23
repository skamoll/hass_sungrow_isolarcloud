"""DataUpdateCoordinator for Sungrow iSolarCloud."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from py_sungrow_isolarcloud import (
    ISolarCloudApiError,
    ISolarCloudAuthError,
    ISolarCloudClient,
    ISolarCloudConnectionError,
    ISolarCloudError,
    PlantData,
)

from .const import (
    DEFAULT_OFFLINE_NOTIFY_ENABLED,
    DEFAULT_OFFLINE_THRESHOLD_MINUTES,
    DOMAIN,
    MAX_CACHE_STALE_MINUTES,
    MAX_CONSECUTIVE_GRACE_ERRORS,
)

_LOGGER = logging.getLogger(__name__)
RETRY_BACKOFF_SECONDS = (30, 90, 180, 300)
_RATE_LIMIT_MARKERS = ("rate limit", "too many", "429", "e998", "e999", "frequency")


class ISolarCloudCoordinator(DataUpdateCoordinator[dict[str, PlantData]]):
    """Coordinator that polls iSolarCloud once per interval for all plants."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ISolarCloudClient,
        scan_interval_seconds: int,
        offline_notify_enabled: bool = DEFAULT_OFFLINE_NOTIFY_ENABLED,
        offline_threshold_minutes: int = DEFAULT_OFFLINE_THRESHOLD_MINUTES,
        notify_service: str = "",
        entry_id: str = "",
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.client = client
        self.last_sync_utc: datetime | None = None
        self.plant_device_ids: dict[str, str] = {}
        self._base_interval = timedelta(seconds=scan_interval_seconds)
        self._max_cache_age = max(
            self._base_interval * 3,
            timedelta(minutes=MAX_CACHE_STALE_MINUTES),
        )
        self.offline_notify_enabled = offline_notify_enabled
        self.offline_threshold = timedelta(minutes=max(1, offline_threshold_minutes))
        self.notify_service = notify_service.strip()
        self._entry_id = entry_id
        self.consecutive_errors = 0
        self.last_error: str | None = None
        self._offline_since: dict[str, datetime] = {}
        self._notified_offline: set[str] = set()

    @property
    def _issue_suffix(self) -> str:
        if self._entry_id:
            return self._entry_id
        if self.config_entry is not None:
            return self.config_entry.entry_id
        return "default"

    def _next_retry_interval(self) -> timedelta:
        """Return progressive backoff interval capped at 300s (or base interval if larger)."""
        idx = min(max(self.consecutive_errors - 1, 0), len(RETRY_BACKOFF_SECONDS) - 1)
        return max(self._base_interval, timedelta(seconds=RETRY_BACKOFF_SECONDS[idx]))

    def _can_serve_grace_cache(self) -> bool:
        """Return True when recent cached data can mask a brief transient outage."""
        if (
            self.data is None
            or self.last_sync_utc is None
            or self.consecutive_errors > MAX_CONSECUTIVE_GRACE_ERRORS
        ):
            return False
        return (dt_util.utcnow() - self.last_sync_utc) <= self._max_cache_age

    def _update_error_repairs(self, err_text: str) -> None:
        """Surface sustained outages or rate-limiting as native Home Assistant Repairs."""
        lowered = err_text.lower()
        if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"rate_limited_{self._issue_suffix}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="rate_limited",
                translation_placeholders={
                    "interval": str(int(self._base_interval.total_seconds())),
                },
            )
            return

        if self.consecutive_errors > MAX_CONSECUTIVE_GRACE_ERRORS:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"connection_outage_{self._issue_suffix}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="connection_outage",
                translation_placeholders={
                    "error_count": str(self.consecutive_errors),
                    "last_error": err_text[:180],
                },
            )

    def _clear_error_repairs(self) -> None:
        """Clear transient outage and rate-limit Repair issues on recovery."""
        ir.async_delete_issue(self.hass, DOMAIN, f"connection_outage_{self._issue_suffix}")
        ir.async_delete_issue(self.hass, DOMAIN, f"rate_limited_{self._issue_suffix}")

    async def _async_update_data(self) -> dict[str, PlantData]:
        start = time.monotonic()
        _LOGGER.debug(
            "Starting iSolarCloud poll (interval=%ss, offline_notify=%s, threshold=%s)",
            int(self.update_interval.total_seconds()) if self.update_interval else None,
            self.offline_notify_enabled,
            self.offline_threshold,
        )
        try:
            data = await self.client.async_fetch_all_plants()
        except ISolarCloudAuthError as err:
            self.consecutive_errors += 1
            self.last_error = f"{type(err).__name__}: {err}"
            _LOGGER.error(
                "iSolarCloud authentication failed (attempt #%d): %s",
                self.consecutive_errors,
                err,
            )
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except (ISolarCloudConnectionError, ISolarCloudApiError, ISolarCloudError) as err:
            self.consecutive_errors += 1
            self.last_error = f"{type(err).__name__}: {err}"
            self.update_interval = self._next_retry_interval()
            if self._can_serve_grace_cache():
                _LOGGER.warning(
                    "Transient iSolarCloud error (attempt #%d/%d, serving cached data, "
                    "next_retry=%ss): %s",
                    self.consecutive_errors,
                    MAX_CONSECUTIVE_GRACE_ERRORS,
                    int(self.update_interval.total_seconds()),
                    self.last_error,
                )
                return self.data
            self._update_error_repairs(self.last_error)
            _LOGGER.debug(
                "iSolarCloud poll failed (attempt #%d, elapsed=%.2fs, next_retry=%ss): %s",
                self.consecutive_errors,
                time.monotonic() - start,
                int(self.update_interval.total_seconds()),
                self.last_error,
            )
            raise UpdateFailed(f"Error communicating with iSolarCloud: {err}") from err
        except Exception as err:
            self.consecutive_errors += 1
            self.last_error = f"{type(err).__name__}: {err}"
            self.update_interval = self._next_retry_interval()
            if self._can_serve_grace_cache():
                _LOGGER.warning(
                    "Unexpected transient error polling iSolarCloud (attempt #%d/%d, "
                    "serving cached data, next_retry=%ss): %s",
                    self.consecutive_errors,
                    MAX_CONSECUTIVE_GRACE_ERRORS,
                    int(self.update_interval.total_seconds()),
                    self.last_error,
                )
                return self.data
            self._update_error_repairs(self.last_error)
            _LOGGER.exception(
                "Unexpected error polling iSolarCloud (attempt #%d, elapsed=%.2fs, next_retry=%ss)",
                self.consecutive_errors,
                time.monotonic() - start,
                int(self.update_interval.total_seconds()),
            )
            raise UpdateFailed(f"Unexpected iSolarCloud error: {err}") from err

        elapsed = time.monotonic() - start
        if self.consecutive_errors > 0:
            self.update_interval = self._base_interval
            self._clear_error_repairs()
            _LOGGER.info(
                "iSolarCloud connection recovered after %d failed poll(s); "
                "resuming %ss schedule (elapsed=%.2fs)",
                self.consecutive_errors,
                int(self._base_interval.total_seconds()),
                elapsed,
            )
            self.consecutive_errors = 0
            self.last_error = None

        self.last_sync_utc = dt_util.utcnow()
        if not data:
            _LOGGER.warning("iSolarCloud returned 0 plants during poll (elapsed=%.2fs)", elapsed)
        else:
            for ps_id, plant in data.items():
                _LOGGER.debug(
                    "Plant %s (%s): online=%s status=%s pv=%s%s load=%s "
                    "devices=%d faults=%d last_update=%s (elapsed=%.2fs)",
                    ps_id,
                    plant.summary.ps_name,
                    plant.summary.is_online,
                    plant.summary.ps_status,
                    plant.flow.pv_power.value if plant.flow.pv_power else None,
                    plant.flow.pv_power.unit if plant.flow.pv_power else None,
                    plant.flow.load_power.value if plant.flow.load_power else None,
                    len(plant.devices),
                    len(plant.active_faults),
                    plant.flow.last_update_time,
                    elapsed,
                )

        await self._async_check_offline_plants(data)
        return data

    async def _async_check_offline_plants(self, data: dict[str, PlantData]) -> None:
        """Track plant offline durations and manage persistent/push notifications & Repairs."""
        now = dt_util.utcnow()
        is_es = (self.hass.config.language or "").lower().startswith("es")

        for ps_id, plant in data.items():
            notification_id = f"{DOMAIN}_offline_{ps_id}"
            repair_id = f"plant_offline_{ps_id}"
            if not plant.summary.is_online:
                offline_since = self._offline_since.get(ps_id)
                if offline_since is None:
                    self._offline_since[ps_id] = now
                    _LOGGER.warning(
                        "Plant PV %s (%s) reported offline at %s",
                        ps_id,
                        plant.summary.ps_name,
                        now.isoformat(),
                    )
                    continue

                offline_duration = now - offline_since
                _LOGGER.debug(
                    "Plant PV %s still offline (duration=%s, threshold=%s, notified=%s)",
                    ps_id,
                    offline_duration,
                    self.offline_threshold,
                    ps_id in self._notified_offline,
                )
                if (
                    self.offline_notify_enabled
                    and ps_id not in self._notified_offline
                    and offline_duration >= self.offline_threshold
                ):
                    self._notified_offline.add(ps_id)
                    mins = int(offline_duration.total_seconds() // 60)
                    title = (
                        f"Planta solar PV {ps_id} sin conexión"
                        if is_es
                        else f"Solar plant PV {ps_id} offline"
                    )
                    message = (
                        f"La planta PV {ps_id} lleva {mins} minuto(s) desconectada en iSolarCloud."
                        if is_es
                        else (
                            f"Plant PV {ps_id} has been offline in iSolarCloud "
                            f"for {mins} minute(s)."
                        )
                    )
                    _LOGGER.warning(
                        "Triggering offline notification & Repair for PV %s (offline for %d min)",
                        ps_id,
                        mins,
                    )
                    persistent_notification.async_create(
                        self.hass,
                        message=message,
                        title=title,
                        notification_id=notification_id,
                    )
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        repair_id,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="plant_offline",
                        translation_placeholders={"ps_id": ps_id, "minutes": str(mins)},
                    )
                    await self._async_send_notify_service(title, message)
            else:
                offline_since = self._offline_since.pop(ps_id, None)
                if offline_since is not None:
                    duration = now - offline_since
                    _LOGGER.info("Plant PV %s is back online after %s", ps_id, duration)
                if ps_id in self._notified_offline:
                    self._notified_offline.discard(ps_id)
                    persistent_notification.async_dismiss(self.hass, notification_id)
                    ir.async_delete_issue(self.hass, DOMAIN, repair_id)
                    title = (
                        f"Planta solar PV {ps_id} en línea"
                        if is_es
                        else f"Solar plant PV {ps_id} back online"
                    )
                    message = (
                        f"La planta PV {ps_id} ha recuperado la conexión en iSolarCloud."
                        if is_es
                        else f"Plant PV {ps_id} is back online in iSolarCloud."
                    )
                    await self._async_send_notify_service(title, message)

    async def _async_send_notify_service(self, title: str, message: str) -> None:
        """Send an optional Home Assistant notify.* service call."""
        if not self.notify_service:
            return
        service_name = self.notify_service.removeprefix("notify.").strip()
        if not service_name:
            return
        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {"title": title, "message": message},
                blocking=False,
            )
            _LOGGER.debug("Sent notification via notify.%s: %s", service_name, title)
        except Exception as err:
            _LOGGER.warning(
                "Failed to send notification via notify.%s: %s",
                service_name,
                err,
            )
