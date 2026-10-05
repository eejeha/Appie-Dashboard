"""Tests for the standalone API client."""

from __future__ import annotations

import time
from datetime import date

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.appie.api import (
    BASE_URL,
    AppieAuthError,
    AppieClient,
    ShoppingListItem,
    Tokens,
    extract_code,
)


def _tokens(expired: bool = False) -> Tokens:
    return Tokens("access", "refresh", time.time() + (-10 if expired else 3600), "1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("abc123", "abc123"),
        ("appie://login-exit?code=xyz&state=1", "xyz"),
        ("  appie://login-exit?code=xyz  ", "xyz"),
        ("code=qq", "qq"),
    ],
)
def test_extract_code(value, expected):
    assert extract_code(value) == expected


@pytest.mark.parametrize("value", ["", "appie://login-exit?state=1", "not a code"])
def test_extract_code_invalid(value):
    with pytest.raises(ValueError):
        extract_code(value)


async def test_exchange_code_and_callback():
    saved = []
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, on_tokens_updated=saved.append)
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/mobile-auth/v1/auth/token",
                payload={"access_token": "a", "refresh_token": "r", "member_id": 42, "expires_in": 3600},
            )
            tokens = await client.async_exchange_code("code")
    assert tokens.access_token == "a"
    assert tokens.member_id == "42"
    assert saved == [tokens]


async def test_expired_token_is_refreshed():
    saved = []
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, _tokens(expired=True), on_tokens_updated=saved.append)
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/mobile-auth/v1/auth/token/refresh",
                payload={"access_token": "new", "refresh_token": "r2", "expires_in": 3600},
            )
            m.get(f"{BASE_URL}/mobile-services/shoppinglist/v2/items", payload={"items": []})
            await client.async_get_shopping_list()
            request = m.requests[("GET", aiohttp.client.URL(f"{BASE_URL}/mobile-services/shoppinglist/v2/items"))][0]
    assert request.kwargs["headers"]["Authorization"] == "Bearer new"
    assert client.tokens.member_id == "1"
    assert len(saved) == 1


async def test_401_retries_once_then_auth_error():
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, _tokens())
        with aioresponses() as m:
            m.get(f"{BASE_URL}/mobile-services/shoppinglist/v2/items", status=401)
            m.post(f"{BASE_URL}/mobile-auth/v1/auth/token/refresh", status=400, payload={"code": "x"})
            with pytest.raises(AppieAuthError):
                await client.async_get_shopping_list()


async def test_shopping_list_parse_and_patch():
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, _tokens())
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/mobile-services/shoppinglist/v2/items",
                payload={
                    "items": [
                        {"strikedthrough": False, "quantity": 1, "description": "vegan shoarma",
                         "type": "SHOPPABLE", "originCode": "TXT", "position": 32},
                        {"strikedthrough": True, "quantity": 2, "description": "AH Woksaus",
                         "type": "SHOPPABLE", "originCode": "PRD", "productId": 482500},
                    ]
                },
            )
            m.patch(f"{BASE_URL}/mobile-services/shoppinglist/v2/items", payload={})
            items = await client.async_get_shopping_list()
            await client.async_patch_shopping_list([ShoppingListItem("AH Woksaus", 0, True, "PRD", product_id=482500)])
            body = list(m.requests.values())[-1][0].kwargs["json"]
    assert items[0].uid == "text:vegan shoarma"
    assert items[1].uid == "product:482500"
    assert items[1].checked and items[1].quantity == 2
    assert body == {
        "items": [
            {"description": "AH Woksaus", "quantity": 0, "type": "SHOPPABLE", "originCode": "PRD",
             "strikeThrough": True, "productId": 482500, "searchTerm": "AH Woksaus"}
        ]
    }


async def test_receipts_sorted_newest_first():
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, _tokens())
        with aioresponses() as m:
            m.post(
                f"{BASE_URL}/graphql",
                payload={"data": {"posReceiptsPage": {"posReceipts": [
                    {"id": "a", "dateTime": "2026-09-01T10:00:00Z", "totalAmount": {"amount": 10.5}},
                    {"id": "b", "dateTime": "2026-10-01T10:00:00Z", "totalAmount": {"amount": 3}},
                ]}}},
            )
            receipts = await client.async_get_receipts()
    assert [r.id for r in receipts] == ["b", "a"]
    assert receipts[1].total == 10.5


async def test_active_order_404_is_none_and_sets_header():
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, _tokens())
        url = f"{BASE_URL}/mobile-services/order/v1/summaries/active?sortBy=DEFAULT"
        with aioresponses() as m:
            m.get(url, status=404, body="not found")
            assert await client.async_get_active_order() is None
            m.get(url, payload={
                "id": 77, "state": "NEW",
                "totalPrice": {"priceTotalPayable": 20.0, "priceDiscount": 1.5},
                "deliveryInformation": {"deliveryDate": "2026-10-06"},
                "orderedProducts": [{"quantity": 3, "product": {"webshopId": 5, "title": "Melk"}}],
            })
            order = await client.async_get_active_order()
            m.put(f"{BASE_URL}/mobile-services/order/v1/items?sortBy=DEFAULT", payload={})
            await client.async_update_order({5: 4})
            put = list(m.requests.values())[-1][0]
    assert order.id == 77 and order.total == 20.0 and order.items[0].quantity == 3
    assert put.kwargs["headers"]["appie-current-order-id"] == "77"
    assert put.kwargs["json"]["items"][0] == {
        "productId": 5, "quantity": 4, "originCode": "PRD", "description": "", "strikethrough": False
    }


async def test_bonus_overview():
    async with aiohttp.ClientSession() as session:
        client = AppieClient(session, _tokens())
        with aioresponses() as m:
            m.get(
                f"{BASE_URL}/mobile-services/bonuspage/v3/metadata",
                payload={"periods": [
                    {"bonusStartDate": "2026-10-05", "bonusEndDate": "2026-10-11", "tabs": [
                        {"urlMetadataList": [
                            {"bonusType": "NATIONAL", "count": 100},
                            {"bonusType": "PERSONAL", "count": 5},
                            {"bonusType": "NATIONAL", "count": 20},
                        ]}]},
                    {"bonusStartDate": "2026-10-12", "bonusEndDate": "2026-10-18", "tabs": []},
                ]},
            )
            m.get(
                f"{BASE_URL}/mobile-services/bonuspage/v2/section/spotlight?application=AHWEBSHOP&date=2026-10-06",
                payload={"bonusGroupOrProducts": [
                    {"product": {"title": "Kaas", "bonusMechanism": "1+1", "currentPrice": 4, "webshopId": 1}},
                    {"bonusGroup": {"segmentDescription": "Alle Hak", "discountDescription": "2e halve prijs"}},
                ]},
            )
            bonus = await client.async_get_bonus(date(2026, 10, 6))
    assert bonus.total_count == 120
    assert bonus.start_date == "2026-10-05"
    assert [p.title for p in bonus.spotlight] == ["Kaas", "Alle Hak"]
