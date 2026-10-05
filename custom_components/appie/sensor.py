"""Bonus and receipt sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import AppieConfigEntry, BonusCoordinator, ReceiptsCoordinator
from .entity import device_info
from .models import SOURCE_PERSONAL

RECENT_RECEIPTS = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    async_add_entities(
        [
            BonusSensor(entry, data.bonus),
            LatestReceiptSensor(entry, data.receipts),
            MonthSpendSensor(entry, data.receipts),
        ]
    )


class _Base(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: AppieConfigEntry, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_name = name
        self._attr_device_info = device_info(entry)


class BonusSensor(_Base, SensorEntity):
    """Number of relevant bonus offers; the offers themselves as attribute."""

    _attr_icon = "mdi:sale"
    _attr_native_unit_of_measurement = "aanbiedingen"
    # The offer list is big and changes weekly; keep it out of the database.
    _unrecorded_attributes = frozenset({"offers"})

    def __init__(self, entry: AppieConfigEntry, coordinator: BonusCoordinator) -> None:
        super().__init__(entry, coordinator, "bonus_voor_ons", "Bonus voor ons")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.offers)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "period_start": data.period_start,
            "period_end": data.period_end,
            "on_list": sum(o.on_list for o in data.offers),
            "personal": sum(o.source == SOURCE_PERSONAL for o in data.offers),
            "offers": [o.as_dict() for o in data.offers],
        }


class LatestReceiptSensor(_Base, SensorEntity):
    """Total of the most recent in-store receipt."""

    _attr_icon = "mdi:receipt-text"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _unrecorded_attributes = frozenset({"items", "discounts", "recent"})

    def __init__(self, entry: AppieConfigEntry, coordinator: ReceiptsCoordinator) -> None:
        super().__init__(entry, coordinator, "laatste_kassabon", "Laatste kassabon")

    @property
    def native_value(self) -> float | None:
        latest = self.coordinator.data.latest
        return latest.total if latest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        detail = data.latest_detail
        return {
            "datetime": data.latest.local(dt_util.get_default_time_zone()).isoformat() if data.latest else None,
            "items": detail.items if detail else [],
            "discounts": detail.discounts if detail else [],
            "discount_total": detail.discount_total if detail else None,
            "payments": detail.payments if detail else [],
            "recent": [
                {"datetime": r.local(dt_util.get_default_time_zone()).isoformat(), "total": r.total}
                for r in data.receipts[:RECENT_RECEIPTS]
            ],
        }


class MonthSpendSensor(_Base, SensorEntity):
    """Sum of this month's receipts; resets on the 1st."""

    _attr_icon = "mdi:cart-outline"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"

    def __init__(self, entry: AppieConfigEntry, coordinator: ReceiptsCoordinator) -> None:
        super().__init__(entry, coordinator, "uitgaven_deze_maand", "Uitgaven deze maand")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.month_total

    @property
    def last_reset(self) -> datetime:
        return dt_util.start_of_local_day(dt_util.now().replace(day=1))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"receipts": self.coordinator.data.month_count}
