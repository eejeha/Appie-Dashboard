"""Config flow: log in on login.ah.nl and paste the appie://login-exit link."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AppieAuthError, AppieError, exchange_code, extract_code, member_id
from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN, DOMAIN, LOGIN_URL

_LOGGER = logging.getLogger(__name__)

CONF_LOGIN_LINK = "login_link"
SCHEMA = vol.Schema({vol.Required(CONF_LOGIN_LINK): str})


class AppieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the login."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, error = await self._login(user_input[CONF_LOGIN_LINK])
            if tokens:
                await self.async_set_unique_id(member_id(tokens["access_token"]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Albert Heijn", data=_entry_data(tokens))
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": LOGIN_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, error = await self._login(user_input[CONF_LOGIN_LINK])
            if tokens:
                await self.async_set_unique_id(member_id(tokens["access_token"]))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=_entry_data(tokens)
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": LOGIN_URL},
        )

    async def _login(self, link: str) -> tuple[dict[str, Any] | None, str]:
        try:
            code = extract_code(link)
        except ValueError:
            return None, "invalid_link"
        try:
            return await exchange_code(async_get_clientsession(self.hass), code), ""
        except AppieAuthError:
            return None, "code_expired"
        except AppieError:
            _LOGGER.exception("login failed")
            return None, "cannot_connect"


def _entry_data(tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_ACCESS_TOKEN: tokens["access_token"],
        CONF_REFRESH_TOKEN: tokens["refresh_token"],
        CONF_EXPIRES_AT: tokens["expires_at"],
    }
