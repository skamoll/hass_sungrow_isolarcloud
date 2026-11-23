"""Constants for the Sungrow iSolarCloud integration."""

from __future__ import annotations

DOMAIN = "hass_sungrow_isolarcloud"

CONF_GATEWAY = "gateway"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_OFFLINE_NOTIFY_ENABLED = "offline_notify_enabled"
CONF_OFFLINE_THRESHOLD_MINUTES = "offline_threshold_minutes"
CONF_NOTIFY_SERVICE = "notify_service"

DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 600

DEFAULT_OFFLINE_NOTIFY_ENABLED = True
DEFAULT_OFFLINE_THRESHOLD_MINUTES = 15
MIN_OFFLINE_THRESHOLD_MINUTES = 1
MAX_OFFLINE_THRESHOLD_MINUTES = 1440
