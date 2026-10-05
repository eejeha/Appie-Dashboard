"""Shared fixtures."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.appie.api import (
    BonusOverview,
    BonusProduct,
    Fulfillment,
    Order,
    OrderLine,
    Receipt,
    ShoppingListItem,
)
from custom_components.appie.const import CONF_TOKENS, DOMAIN
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

TOKENS = {
    "access_token": "access",
    "refresh_token": "refresh",
    "expires_at": time.time() + 3600,
    "member_id": "12345",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, unique_id="12345", title="Albert Heijn", data={CONF_TOKENS: TOKENS}
    )


@pytest.fixture
def mock_client():
    now = dt_util.now()
    with patch("custom_components.appie.AppieClient", autospec=True) as cls:
        client = cls.return_value
        client.async_get_shopping_list = AsyncMock(
            return_value=[
                ShoppingListItem("melk", 2, False, "TXT"),
                ShoppingListItem("AH Woksaus", 1, True, "PRD", product_id=482500),
            ]
        )
        client.async_get_receipts = AsyncMock(
            return_value=[Receipt("r1", now, 12.5), Receipt("r2", now, 7.25)]
        )
        client.async_get_active_order = AsyncMock(
            return_value=Order(1, "NEW", 30.0, 2.0, None, None, None, [OrderLine(482500, "AH Woksaus", 2)])
        )
        client.async_get_fulfillments = AsyncMock(
            return_value=[
                Fulfillment(9, "Bezorgd morgen", "DELIVERY", True, 55.0, "2026-10-06", "18:00", "20:00", "18:00 - 20:00")
            ]
        )
        client.async_get_bonus = AsyncMock(
            return_value=BonusOverview(
                "2026-10-05", "2026-10-11", 321, [BonusProduct("Kaas", "1+1 gratis", 4.0, 8.0, 1, "Zuivel")]
            )
        )
        client.async_patch_shopping_list = AsyncMock()
        client.async_update_order = AsyncMock()
        yield client
