"""Diagnostics with the tokens left out."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN
from .coordinator import AppieConfigEntry

TO_REDACT = {CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AppieConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    receipts = data.receipts.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "list": [asdict(i) for i in data.shopping_list.data or []],
        "bonus": asdict(data.bonus.data) if data.bonus.data else None,
        "favorites": [asdict(f) for f in data.favorites.data or []],
        "receipts": {
            "count": len(receipts.receipts),
            "month_total": receipts.month_total,
            "latest_items": len(receipts.latest_detail.items) if receipts.latest_detail else 0,
        }
        if receipts
        else None,
    }
