"""Config flow for the Tuya Project Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaConnectionError,
    TuyaOpenApi,
)
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_ENABLE_CAMERA,
    CONF_ENABLE_SHADOW,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENABLE_CAMERA,
    DEFAULT_ENABLE_SHADOW,
    DOMAIN,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)

# Selector labels come from translations, so the stored value stays a plain
# region code while the user sees a readable name in every language.
REGION_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(options=list(REGIONS), translation_key="region")
)

REGION_TITLES: dict[str, dict[str, str]] = {
    "de": {
        "cn": "China",
        "us": "USA (West)",
        "us_east": "USA (Ost)",
        "eu": "Europa (Zentral)",
        "eu_west": "Europa (West)",
        "in": "Indien",
        "sg": "Singapur",
    },
    "en": {
        "cn": "China",
        "us": "United States (West)",
        "us_east": "United States (East)",
        "eu": "Europe (Central)",
        "eu_west": "Europe (West)",
        "in": "India",
        "sg": "Singapore",
    },
}


def _region_title(language: str, region: str) -> str:
    """Build a human-readable config entry title for a region code."""
    labels = REGION_TITLES.get(language.split("-", 1)[0].lower(), REGION_TITLES["en"])
    return f"Tuya Cloud ({labels.get(region, region)})"


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCESS_ID): str,
        vol.Required(CONF_ACCESS_SECRET): str,
        vol.Required(CONF_REGION, default="eu"): REGION_SELECTOR,
    }
)


class TuyaProjectCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya Project Cloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: project credentials only."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = TuyaOpenApi(
                async_get_clientsession(self.hass),
                user_input[CONF_ACCESS_ID],
                user_input[CONF_ACCESS_SECRET],
                user_input[CONF_REGION],
            )
            try:
                await client.async_validate()
            except TuyaAuthenticationError:
                errors["base"] = "invalid_auth"
            except TuyaConnectionError:
                errors["base"] = "cannot_connect"
            except TuyaApiError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_ACCESS_ID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_region_title(
                        self.hass.config.language, user_input[CONF_REGION]
                    ),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication after invalid credentials.

        Home Assistant may pass the old entry data here. Never validate stale
        credentials; always show the form and let the user enter new values.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials without asking for an app account."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            client = TuyaOpenApi(
                async_get_clientsession(self.hass),
                user_input[CONF_ACCESS_ID],
                user_input[CONF_ACCESS_SECRET],
                user_input[CONF_REGION],
            )
            try:
                await client.async_validate()
            except TuyaAuthenticationError:
                errors["base"] = "invalid_auth"
            except TuyaConnectionError:
                errors["base"] = "cannot_connect"
            except TuyaApiError:
                errors["base"] = "unknown"
            else:
                new_id = user_input[CONF_ACCESS_ID]
                if new_id != entry.data.get(CONF_ACCESS_ID) and any(
                    other.unique_id == new_id and other.entry_id != entry.entry_id
                    for other in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    data=user_input,
                    unique_id=new_id,
                    title=_region_title(
                        self.hass.config.language, user_input[CONF_REGION]
                    ),
                )

        defaults = {
            CONF_ACCESS_ID: entry.data.get(CONF_ACCESS_ID, ""),
            CONF_REGION: entry.data.get(CONF_REGION, "eu"),
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_ACCESS_ID, default=defaults[CONF_ACCESS_ID]): str,
                vol.Required(CONF_ACCESS_SECRET): str,
                vol.Required(
                    CONF_REGION, default=defaults[CONF_REGION]
                ): REGION_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: Any,
    ) -> TuyaProjectCloudOptionsFlow:
        """Return the options flow."""
        return TuyaProjectCloudOptionsFlow()


class TuyaProjectCloudOptionsFlow(OptionsFlowWithReload):
    """Options for polling, shadow data and the camera platform."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options; saving reloads the entry automatically."""
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, 30),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=900)),
                vol.Optional(
                    CONF_ENABLE_SHADOW,
                    default=options.get(CONF_ENABLE_SHADOW, DEFAULT_ENABLE_SHADOW),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_CAMERA,
                    default=options.get(CONF_ENABLE_CAMERA, DEFAULT_ENABLE_CAMERA),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
