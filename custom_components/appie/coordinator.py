"""Data update coordinators for the Albert Heijn integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AppieAuthError,
    AppieClient,
    AppieError,
    BonusOverview,
    Fulfillment,
    Order,
    Receipt,
    ShoppingListItem,
)
from .const import BONUS_UPDATE_INTERVAL, DATA_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class AppieData:
    shopping_list: list[ShoppingListItem] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    order: Order | None = None
    fulfillments: list[Fulfillment] = field(default_factory=list)


@dataclass
class AppieRuntimeData:
    client: AppieClient
    coordinator: AppieCoordinator
    bonus_coordinator: AppieBonusCoordinator


type AppieConfigEntry = ConfigEntry[AppieRuntimeData]


class AppieCoordinator(DataUpdateCoordinator[AppieData]):
    """Polls shopping list, receipts and orders."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AppieClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_data",
            update_interval=DATA_UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> AppieData:
        try:
            shopping_list = await self.client.async_get_shopping_list()
            receipts = await self._optional(self.client.async_get_receipts(), "receipts", [])
            order = await self._optional(self.client.async_get_active_order(), "order", None)
            fulfillments = await self._optional(
                self.client.async_get_fulfillments(), "fulfillments", []
            )
        except AppieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AppieError as err:
            raise UpdateFailed(str(err)) from err
        return AppieData(shopping_list, receipts, order, fulfillments)

    async def _optional(self, coro, name: str, default):
        """Fetch a non-critical part; keep the previous value if it fails."""
        try:
            return await coro
        except AppieAuthError:
            raise
        except AppieError as err:
            _LOGGER.warning("Fetching %s failed: %s", name, err)
            if self.data is not None:
                return getattr(self.data, name)
            return default


class AppieBonusCoordinator(DataUpdateCoordinator[BonusOverview]):
    """Polls the weekly bonus overview."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AppieClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_bonus",
            update_interval=BONUS_UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> BonusOverview:
        try:
            return await self.client.async_get_bonus()
        except AppieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AppieError as err:
            raise UpdateFailed(str(err)) from err
