"""Config flow for Senzomatic integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SenzomaticAPI
from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Senzomatic."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new Central Unit."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = await self._async_probe(user_input[CONF_HOST])
            if api is not None:
                await self.async_set_unique_id(api.unit_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Senzomatic ({user_input[CONF_HOST]})", data=user_input
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Change the IP address of an existing Central Unit."""
        return await self._async_update_host("reconfigure", user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle re-auth (e.g. an old entry with no host key)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the IP address during re-auth."""
        return await self._async_update_host("reauth_confirm", user_input)

    async def _async_update_host(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> FlowResult:
        """Shared host-form handler for reconfigure and reauth."""
        entry: ConfigEntry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            api = await self._async_probe(user_input[CONF_HOST])
            if api is not None:
                return self.async_update_reload_and_abort(
                    entry, unique_id=api.unit_id, data={CONF_HOST: user_input[CONF_HOST]}
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, dict(entry.data)
            ),
            errors=errors,
        )

    async def _async_probe(self, host: str) -> SenzomaticAPI | None:
        """Return an authenticated API client for host, or None if unreachable."""
        api = SenzomaticAPI(async_get_clientsession(self.hass), host)
        if await api.async_authenticate():
            return api
        return None
