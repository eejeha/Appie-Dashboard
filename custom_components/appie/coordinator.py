"""Data update coordinators for the Albert Heijn integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AppieAuthError, AppieClient, AppieError
from .const import (
    BONUS_INTERVAL,
    DOMAIN,
    FAVORITES_COUNT,
    FAVORITES_DAYS,
    FAVORITES_INTERVAL,
    LIST_INTERVAL,
    RECEIPTS_INTERVAL,
    RECEIPTS_PAGE_SIZE,
)
from .models import (
    SOURCE_PERSONAL,
    SOURCE_PREVIOUS,
    BonusOffer,
    Favorite,
    ListItem,
    Receipt,
    ReceiptDetail,
    bonus_period,
    build_favorites,
    month_total,
    parse_bonus_section,
    parse_list,
    parse_receipt_detail,
    parse_receipts,
    rank_purchases,
    receipt_lines,
    relevant_bonus,
)

_LOGGER = logging.getLogger(__name__)

# Receipts are paged; stop after this many pages even if the month is longer.
MAX_RECEIPT_PAGES = 4


@dataclass
class AppieData:
    """Runtime data stored on the config entry."""

    client: AppieClient
    shopping_list: ListCoordinator
    bonus: BonusCoordinator
    receipts: ReceiptsCoordinator
    favorites: FavoritesCoordinator


type AppieConfigEntry = ConfigEntry[AppieData]


class _AppieCoordinator[T](DataUpdateCoordinator[T]):
    """Shared error handling."""

    def __init__(self, hass: HomeAssistant, entry: AppieConfigEntry, client: AppieClient, name: str, interval) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {name}", update_interval=interval
        )
        self.client = client

    async def _async_update_data(self) -> T:
        try:
            return await self._fetch()
        except AppieAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AppieError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> T:
        raise NotImplementedError


class ListCoordinator(_AppieCoordinator[list[ListItem]]):
    """The shopping list, polled every minute for two-way sync."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "boodschappenlijst", LIST_INTERVAL)

    async def _fetch(self) -> list[ListItem]:
        return parse_list(await self.client.get_list() or {})


@dataclass
class BonusData:
    offers: list[BonusOffer]
    period_start: str | None
    period_end: str | None


class BonusCoordinator(_AppieCoordinator[BonusData]):
    """Bonus relevant to us; matched against the list on every list update."""

    def __init__(self, hass, entry, client, shopping_list: ListCoordinator) -> None:
        super().__init__(hass, entry, client, "bonus", BONUS_INTERVAL)
        self._list = shopping_list
        self._personal: list[BonusOffer] = []
        self._previous: list[BonusOffer] = []
        self._period: tuple[str | None, str | None] = (None, None)

    async def _fetch(self) -> BonusData:
        today = dt_util.now().date()
        start, end = bonus_period(await self.client.get_bonus_metadata() or {})
        start = start or today.isoformat()
        self._period = (start, end)
        self._personal = parse_bonus_section(await self.client.get_personal_bonus(start) or {}, SOURCE_PERSONAL)
        self._previous = parse_bonus_section(
            await self.client.get_previously_bought_bonus(today) or {}, SOURCE_PREVIOUS
        )
        return self._merge()

    def _merge(self) -> BonusData:
        return BonusData(
            offers=relevant_bonus(list(self._personal), list(self._previous), self._list.data or []),
            period_start=self._period[0],
            period_end=self._period[1],
        )

    def list_changed(self) -> None:
        """Re-match against the list without calling AH again."""
        if self.data is None:
            return
        # A new bonus week starts on Monday; fetch fresh offers once it has.
        end = self._period[1]
        if end and dt_util.now().date() > date.fromisoformat(end):
            self.hass.async_create_task(self.async_request_refresh())
            return
        self.async_set_updated_data(self._merge())


@dataclass
class ReceiptsData:
    receipts: list[Receipt]
    latest: Receipt | None
    latest_detail: ReceiptDetail | None
    month_total: float
    month_count: int


class ReceiptsCoordinator(_AppieCoordinator[ReceiptsData]):
    """In-store receipts (kassabonnen)."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "kassabonnen", RECEIPTS_INTERVAL)
        self._details: dict[str, ReceiptDetail] = {}

    async def _fetch(self) -> ReceiptsData:
        tz = dt_util.get_default_time_zone()
        today = dt_util.now().date()
        month_start = today.replace(day=1)
        receipts: list[Receipt] = []
        for page in range(MAX_RECEIPT_PAGES):
            batch = parse_receipts(await self.client.get_receipts(page * RECEIPTS_PAGE_SIZE, RECEIPTS_PAGE_SIZE))
            receipts.extend(batch)
            if len(batch) < RECEIPTS_PAGE_SIZE or batch[-1].day(tz) < month_start:
                break
        receipts.sort(key=lambda r: r.when, reverse=True)
        latest = receipts[0] if receipts else None
        if latest and latest.id not in self._details:
            self._details = {latest.id: parse_receipt_detail(await self.client.get_receipt_detail(latest.id))}
        this_month = [r for r in receipts if r.day(tz) >= month_start]
        return ReceiptsData(
            receipts=receipts,
            latest=latest,
            latest_detail=self._details.get(latest.id) if latest else None,
            month_total=month_total(receipts, today, tz),
            month_count=len(this_month),
        )


class FavoritesCoordinator(_AppieCoordinator[list[Favorite]]):
    """What we buy most, counted over the receipts of the last months.

    Receipt lines never change, so they are kept in HA storage and each
    receipt is fetched only once.
    """

    STORAGE_VERSION = 1
    # Fetch at most this many new receipts per update (the first run catches up).
    MAX_NEW_RECEIPTS = 120
    CANDIDATES = 2 * FAVORITES_COUNT

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, "vaak gekocht", FAVORITES_INTERVAL)
        self._store: Store[dict] = Store(hass, self.STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.receipt_lines")
        self._lines: dict[str, list] | None = None

    async def _fetch(self) -> list[Favorite]:
        if self._lines is None:
            self._lines = ((await self._store.async_load()) or {}).get("lines", {})
        tz = dt_util.get_default_time_zone()
        since = dt_util.now().date() - timedelta(days=FAVORITES_DAYS)
        receipts: list[Receipt] = []
        for page in range(MAX_RECEIPT_PAGES):
            batch = parse_receipts(await self.client.get_receipts(page * RECEIPTS_PAGE_SIZE, RECEIPTS_PAGE_SIZE))
            receipts.extend(batch)
            if len(batch) < RECEIPTS_PAGE_SIZE or batch[-1].day(tz) < since:
                break
        recent = [r for r in receipts if r.day(tz) >= since]
        missing = [r.id for r in recent if r.id not in self._lines][: self.MAX_NEW_RECEIPTS]
        for receipt_id in missing:
            self._lines[receipt_id] = receipt_lines(await self.client.get_receipt_detail(receipt_id))
        keep = {r.id for r in recent}
        self._lines = {k: v for k, v in self._lines.items() if k in keep}
        if missing:
            await self._store.async_save({"lines": self._lines})

        ranked = rank_purchases([self._lines[r.id] for r in recent if r.id in self._lines])
        candidates = ranked[: self.CANDIDATES]
        webshop_ids = await self.client.convert_pos_ids([pos_id for pos_id, _, _ in candidates])
        products = await self.client.get_products(list(webshop_ids.values()))
        return build_favorites(candidates, webshop_ids, products, FAVORITES_COUNT)
