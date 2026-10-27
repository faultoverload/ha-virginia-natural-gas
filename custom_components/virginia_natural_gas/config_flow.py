"""Config flow for Virginia Natural Gas."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import voluptuous as vol

from .api import CannotConnect, InvalidAuth, VNGClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class VNGConfigFlow(ConfigFlow, domain=DOMAIN):
    """Check the login, then create the entry."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._username = ""
        self._password = ""

    async def _async_login(self) -> dict[str, str]:
        """Log in with the stored credentials; returns form errors (empty on success)."""
        client = VNGClient(
            async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar()),
            self._username,
            self._password,
        )
        try:
            await client.login()
        except InvalidAuth:
            return {"base": "invalid_auth"}
        except CannotConnect:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error logging in")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the portal login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()
            if not (errors := await self._async_login()):
                return self._async_finish()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, {CONF_USERNAME: self._username}
            ),
            errors=errors,
        )

    def _async_finish(self) -> ConfigFlowResult:
        data = {CONF_USERNAME: self._username, CONF_PASSWORD: self._password}
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        return self.async_create_entry(title=self._username, data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauth when the portal rejects the stored password."""
        self._username = entry_data[CONF_USERNAME]
        self._password = entry_data[CONF_PASSWORD]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password and check it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            if not (errors := await self._async_login()):
                return self._async_finish()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={"username": self._username},
            errors=errors,
        )
