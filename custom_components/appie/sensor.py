"""Sensors for the Albert Heijn integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import BonusOverview
from .coordinator import AppieConfigEntry, AppieData
from .entity import AppieEntity


@dataclass(frozen=True, kw_only=True)
class AppieSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Any], Any]
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None


def _local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_local(value)


def _spent_this_month(data: AppieData) -> float:
    now = dt_util.now()
    return round(
        sum(
            r.total
            for r in data.receipts
            if (d := _local(r.datetime)) and d.year == now.year and d.month == now.month
        ),
        2,
    )


def _receipts_this_month(data: AppieData) -> dict[str, Any]:
    now = dt_util.now()
    receipts = [
        r
        for r in data.receipts
        if (d := _local(r.datetime)) and d.year == now.year and d.month == now.month
    ]
    return {"receipt_count": len(receipts)}


def _last_receipt_attrs(data: AppieData) -> dict[str, Any]:
    if not data.receipts:
        return {}
    last = data.receipts[0]
    return {
        "receipt_id": last.id,
        "date": d.isoformat() if (d := _local(last.datetime)) else None,
        "recent_receipts": [
            {
                "date": d.isoformat() if (d := _local(r.datetime)) else None,
                "total": r.total,
            }
            for r in data.receipts[:10]
        ],
    }


def _next_delivery(data: AppieData) -> datetime | None:
    for f in data.fulfillments:
        if not f.date:
            continue
        start = f.start_time or "00:00"
        parsed = dt_util.parse_datetime(f"{f.date}T{start}")
        if parsed is not None:
            return _local(parsed)
    return None


def _next_delivery_attrs(data: AppieData) -> dict[str, Any]:
    if not data.fulfillments:
        return {}
    f = data.fulfillments[0]
    return {
        "order_id": f.order_id,
        "status": f.status,
        "shopping_type": f.shopping_type,
        "modifiable": f.modifiable,
        "total": f.total,
        "time_window": f.time_display,
        "end_time": f.end_time,
        "open_orders": len(data.fulfillments),
    }


def _order_attrs(data: AppieData) -> dict[str, Any]:
    order = data.order
    if order is None:
        return {}
    return {
        "order_id": order.id,
        "state": order.state,
        "discount": order.discount,
        "item_count": sum(i.quantity for i in order.items),
        "delivery_date": order.delivery_date,
        "delivery_start": order.delivery_start,
        "delivery_end": order.delivery_end,
        "items": [
            {"product_id": i.product_id, "title": i.title, "quantity": i.quantity}
            for i in order.items
        ],
    }


def _shopping_list_attrs(data: AppieData) -> dict[str, Any]:
    return {
        "items": [i.description for i in data.shopping_list if not i.checked],
        "checked_items": sum(1 for i in data.shopping_list if i.checked),
    }


def _bonus_attrs(bonus: BonusOverview) -> dict[str, Any]:
    return {
        "period_start": bonus.start_date,
        "period_end": bonus.end_date,
        "spotlight": [
            {
                "title": p.title,
                "mechanism": p.mechanism,
                "price_now": p.price_now,
                "price_was": p.price_was,
                "product_id": p.product_id,
                "category": p.category,
            }
            for p in bonus.spotlight
        ],
    }


DATA_SENSORS: tuple[AppieSensorDescription, ...] = (
    AppieSensorDescription(
        key="shopping_list_open",
        translation_key="shopping_list_open",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(1 for i in d.shopping_list if not i.checked),
        attrs_fn=_shopping_list_attrs,
    ),
    AppieSensorDescription(
        key="last_receipt",
        translation_key="last_receipt",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda d: d.receipts[0].total if d.receipts else None,
        attrs_fn=_last_receipt_attrs,
    ),
    AppieSensorDescription(
        key="spent_this_month",
        translation_key="spent_this_month",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=_spent_this_month,
        attrs_fn=_receipts_this_month,
    ),
    AppieSensorDescription(
        key="order_total",
        translation_key="order_total",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda d: d.order.total if d.order else None,
        attrs_fn=_order_attrs,
    ),
    AppieSensorDescription(
        key="next_delivery",
        translation_key="next_delivery",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_delivery,
        attrs_fn=_next_delivery_attrs,
    ),
)

BONUS_SENSORS: tuple[AppieSensorDescription, ...] = (
    AppieSensorDescription(
        key="bonus_products",
        translation_key="bonus_products",
        value_fn=lambda b: b.total_count,
        attrs_fn=_bonus_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    rt = entry.runtime_data
    entities: list[AppieSensor] = [
        AppieSensor(rt.coordinator, entry, desc) for desc in DATA_SENSORS
    ]
    entities += [AppieSensor(rt.bonus_coordinator, entry, desc) for desc in BONUS_SENSORS]
    async_add_entities(entities)


class AppieSensor(AppieEntity, SensorEntity):
    entity_description: AppieSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: AppieConfigEntry,
        description: AppieSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None or self.coordinator.data is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
