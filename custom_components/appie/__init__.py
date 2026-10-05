"""Albert Heijn: shopping list, bonus and receipts from the AH app."""

from __future__ import annotations

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AppieClient
from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN
from .coordinator import (
    AppieConfigEntry,
    AppieData,
    BonusCoordinator,
    ListCoordinator,
    ReceiptsCoordinator,
)

PLATFORMS = [Platform.SENSOR, Platform.TODO]


async def async_setup_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    """Set up Albert Heijn from a config entry."""

    def save_tokens(tokens: dict[str, Any]) -> None:
        # AH rotates refresh tokens: losing the new one means logging in again.
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: tokens["access_token"],
                CONF_REFRESH_TOKEN: tokens["refresh_token"],
                CONF_EXPIRES_AT: tokens["expires_at"],
            },
        )

    client = AppieClient(
        async_get_clientsession(hass),
        {
            "access_token": entry.data[CONF_ACCESS_TOKEN],
            "refresh_token": entry.data[CONF_REFRESH_TOKEN],
            "expires_at": entry.data.get(CONF_EXPIRES_AT, 0),
        },
        on_tokens=save_tokens,
    )
    shopping_list = ListCoordinator(hass, entry, client)
    bonus = BonusCoordinator(hass, entry, client, shopping_list)
    receipts = ReceiptsCoordinator(hass, entry, client)

    # Sequential on purpose: the first call may refresh the token.
    await shopping_list.async_config_entry_first_refresh()
    await bonus.async_config_entry_first_refresh()
    await receipts.async_config_entry_first_refresh()

    entry.async_on_unload(shopping_list.async_add_listener(bonus.list_changed))
    entry.runtime_data = AppieData(client, shopping_list, bonus, receipts)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
