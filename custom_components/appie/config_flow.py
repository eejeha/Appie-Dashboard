"""Config flow for the Albert Heijn integration.

AH only allows the appie:// redirect URI, so the user logs in via the browser
and copies the authorization code from the final redirect into this flow.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LOGIN_URL, AppieClient, AppieError, extract_code
from .const import CONF_CODE, CONF_TOKENS, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


class AppieConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_login("user", user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_login("reauth_confirm", user_input)

    async def _async_step_login(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                code = extract_code(user_input[CONF_CODE])
            except ValueError:
                errors[CONF_CODE] = "invalid_code"
            else:
                client = AppieClient(async_get_clientsession(self.hass))
                try:
                    tokens = await client.async_exchange_code(code)
                except AppieError as err:
                    _LOGGER.debug("Code exchange failed: %s", err)
                    errors["base"] = "auth_failed"
                except Exception:
                    _LOGGER.exception("Unexpected error during code exchange")
                    errors["base"] = "unknown"
                else:
                    data = {CONF_TOKENS: tokens.as_dict()}
                    if tokens.member_id:
                        await self.async_set_unique_id(tokens.member_id)
                    if self.source == "reauth":
                        entry = self._get_reauth_entry()
                        if tokens.member_id and entry.unique_id:
                            self._abort_if_unique_id_mismatch(reason="wrong_account")
                        return self.async_update_reload_and_abort(entry, data=data)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="Albert Heijn", data=data)

        return self.async_show_form(
            step_id=step_id,
            data_schema=STEP_SCHEMA,
            errors=errors,
            description_placeholders={"login_url": LOGIN_URL},
        )
