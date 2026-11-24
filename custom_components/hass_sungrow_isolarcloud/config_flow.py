"""Config flow and options flow for Sungrow iSolarCloud."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from py_sungrow_isolarcloud import (
    GATEWAY_AUTO,
    GATEWAYS,
    ISolarCloudAuthError,
    ISolarCloudClient,
    ISolarCloudConnectionError,
    ISolarCloudError,
)

from .const import (
    CONF_GATEWAY,
    CONF_NOTIFY_SERVICE,
    CONF_OFFLINE_NOTIFY_ENABLED,
    CONF_OFFLINE_THRESHOLD_MINUTES,
    CONF_SCAN_INTERVAL,
    DEFAULT_OFFLINE_NOTIFY_ENABLED,
    DEFAULT_OFFLINE_THRESHOLD_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_OFFLINE_THRESHOLD_MINUTES,
    MAX_SCAN_INTERVAL,
    MIN_OFFLINE_THRESHOLD_MINUTES,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)
GATEWAY_OPTIONS = [GATEWAY_AUTO, *GATEWAYS.keys()]


class ISolarCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sungrow iSolarCloud."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            gateway = user_input[CONF_GATEWAY]

            _LOGGER.debug("Config flow login attempt (gateway=%s)", gateway)
            session = async_get_clientsession(self.hass)
            client = ISolarCloudClient(
                session=session,
                username=username,
                password=password,
                gateway=gateway,
            )
            try:
                auth = await client.async_login()
                plants = await client.async_get_ps_list()
                _LOGGER.debug("Config flow login succeeded (plants=%d)", len(plants))
            except ISolarCloudAuthError as err:
                _LOGGER.warning("Config flow auth failed (gateway=%s): %s", gateway, err)
                errors["base"] = "invalid_auth"
            except ISolarCloudConnectionError as err:
                _LOGGER.warning("Config flow connection failed (gateway=%s): %s", gateway, err)
                errors["base"] = "cannot_connect"
            except ISolarCloudError as err:
                _LOGGER.error("Config flow iSolarCloud error (gateway=%s): %s", gateway, err)
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow (gateway=%s)", gateway)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"{auth.user_id}:{username.lower()}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"iSolarCloud ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_GATEWAY: gateway,
                    },
                    options={
                        CONF_SCAN_INTERVAL: int(
                            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                        ),
                        CONF_OFFLINE_NOTIFY_ENABLED: DEFAULT_OFFLINE_NOTIFY_ENABLED,
                        CONF_OFFLINE_THRESHOLD_MINUTES: DEFAULT_OFFLINE_THRESHOLD_MINUTES,
                        CONF_NOTIFY_SERVICE: "",
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_GATEWAY, default=GATEWAY_AUTO): SelectSelector(
                    SelectSelectorConfig(
                        options=GATEWAY_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="gateway",
                    )
                ),
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication when credentials expire or become invalid."""
        _LOGGER.debug("Starting reauth flow for entry %s", self.context.get("entry_id"))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm new password during reauthentication."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            username = reauth_entry.data[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            gateway = reauth_entry.data.get(CONF_GATEWAY, GATEWAY_AUTO)

            session = async_get_clientsession(self.hass)
            client = ISolarCloudClient(
                session=session,
                username=username,
                password=password,
                gateway=gateway,
            )
            try:
                await client.async_login()
            except ISolarCloudAuthError as err:
                _LOGGER.warning("Reauth failed (gateway=%s): %s", gateway, err)
                errors["base"] = "invalid_auth"
            except ISolarCloudConnectionError as err:
                _LOGGER.warning("Reauth connection error (gateway=%s): %s", gateway, err)
                errors["base"] = "cannot_connect"
            except ISolarCloudError as err:
                _LOGGER.error("Reauth iSolarCloud error (gateway=%s): %s", gateway, err)
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth (gateway=%s)", gateway)
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: password},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration of gateway or credentials in place."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            raw_password = user_input.get(CONF_PASSWORD) or ""
            password = raw_password if raw_password else reconfigure_entry.data[CONF_PASSWORD]
            gateway = user_input[CONF_GATEWAY]

            _LOGGER.debug(
                "Reconfigure login attempt for entry %s (gateway=%s)",
                reconfigure_entry.entry_id,
                gateway,
            )
            session = async_get_clientsession(self.hass)
            client = ISolarCloudClient(
                session=session,
                username=username,
                password=password,
                gateway=gateway,
            )
            try:
                auth = await client.async_login()
            except ISolarCloudAuthError as err:
                _LOGGER.warning("Reconfigure auth failed (gateway=%s): %s", gateway, err)
                errors["base"] = "invalid_auth"
            except ISolarCloudConnectionError as err:
                _LOGGER.warning("Reconfigure connection failed (gateway=%s): %s", gateway, err)
                errors["base"] = "cannot_connect"
            except ISolarCloudError as err:
                _LOGGER.error("Reconfigure iSolarCloud error (gateway=%s): %s", gateway, err)
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected error during reconfigure (gateway=%s)", gateway)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"{auth.user_id}:{username.lower()}")
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=f"iSolarCloud ({username})",
                    data_updates={
                        CONF_GATEWAY: gateway,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_GATEWAY,
                    default=reconfigure_entry.data.get(CONF_GATEWAY, GATEWAY_AUTO),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=GATEWAY_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="gateway",
                    )
                ),
                vol.Required(
                    CONF_USERNAME,
                    default=reconfigure_entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Optional(CONF_PASSWORD, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ISolarCloudOptionsFlow()


class ISolarCloudOptionsFlow(OptionsFlow):
    """Handle options flow for Sungrow iSolarCloud."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
            notify_service = (user_input.get(CONF_NOTIFY_SERVICE) or "").strip()
            _LOGGER.debug(
                "Updating options: scan_interval=%s, offline_notify=%s, "
                "threshold=%smin, notify_service=%s",
                user_input[CONF_SCAN_INTERVAL],
                user_input[CONF_OFFLINE_NOTIFY_ENABLED],
                user_input[CONF_OFFLINE_THRESHOLD_MINUTES],
                bool(notify_service),
            )
            return self.async_create_entry(
                title="",
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_OFFLINE_NOTIFY_ENABLED: bool(user_input[CONF_OFFLINE_NOTIFY_ENABLED]),
                    CONF_OFFLINE_THRESHOLD_MINUTES: int(user_input[CONF_OFFLINE_THRESHOLD_MINUTES]),
                    CONF_NOTIFY_SERVICE: notify_service,
                },
            )

        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_offline_notify = self.config_entry.options.get(
            CONF_OFFLINE_NOTIFY_ENABLED, DEFAULT_OFFLINE_NOTIFY_ENABLED
        )
        current_offline_threshold = self.config_entry.options.get(
            CONF_OFFLINE_THRESHOLD_MINUTES, DEFAULT_OFFLINE_THRESHOLD_MINUTES
        )
        current_notify_service = self.config_entry.options.get(CONF_NOTIFY_SERVICE, "")

        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current_interval): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(
                    CONF_OFFLINE_NOTIFY_ENABLED, default=current_offline_notify
                ): BooleanSelector(),
                vol.Required(
                    CONF_OFFLINE_THRESHOLD_MINUTES, default=current_offline_threshold
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_OFFLINE_THRESHOLD_MINUTES,
                        max=MAX_OFFLINE_THRESHOLD_MINUTES,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(CONF_NOTIFY_SERVICE, default=current_notify_service): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
