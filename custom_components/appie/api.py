"""Async client for the Albert Heijn mobile API.

Endpoints and headers are based on https://github.com/gwillem/appie-go.
This module has no Home Assistant dependencies so it can be tested standalone.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

BASE_URL = "https://api.ah.nl"
LOGIN_BASE_URL = "https://login.ah.nl"
CLIENT_ID = "appie-ios"
CLIENT_VERSION = "9.28"
APPLICATION = "AHWEBSHOP"
USER_AGENT = "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"
REDIRECT_URI = "appie://login-exit"

# Refresh the access token this many seconds before it actually expires.
TOKEN_EXPIRY_MARGIN = 60

LOGIN_URL = (
    f"{LOGIN_BASE_URL}/login?client_id={CLIENT_ID}"
    f"&response_type=code&redirect_uri={REDIRECT_URI}"
)

_RECEIPTS_QUERY = """query FetchPosReceipts($offset: Int!, $limit: Int!) {
  posReceiptsPage(pagination: {offset: $offset, limit: $limit}) {
    posReceipts {
      id
      dateTime
      totalAmount { amount }
    }
  }
}"""

_FULFILLMENTS_QUERY = """query OrderFulfillments {
  orderFulfillments(status: OPEN) {
    result {
      orderId
      statusDescription
      shoppingType
      modifiable
      totalPrice { totalPrice { amount } }
      delivery {
        status
        method
        slot { date dateDisplay timeDisplay startTime endTime }
      }
    }
  }
}"""


class AppieError(Exception):
    """Generic API error."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AppieAuthError(AppieError):
    """Authentication failed or tokens are no longer valid."""


@dataclass
class Tokens:
    """OAuth tokens for an AH account."""

    access_token: str
    refresh_token: str
    expires_at: float = 0.0
    member_id: str | None = None

    @classmethod
    def from_response(cls, data: dict[str, Any], member_id: str | None = None) -> Tokens:
        expires_in = int(data.get("expires_in") or 0)
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + expires_in if expires_in else 0.0,
            member_id=str(data.get("member_id") or member_id or "") or None,
        )

    @property
    def expired(self) -> bool:
        return bool(self.expires_at) and time.time() >= self.expires_at - TOKEN_EXPIRY_MARGIN

    def as_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "member_id": self.member_id,
        }


@dataclass
class ShoppingListItem:
    """Item on the main AH shopping list (Mijn lijst)."""

    description: str
    quantity: int
    checked: bool
    origin_code: str
    product_id: int | None = None
    position: int | None = None
    type: str = "SHOPPABLE"

    @property
    def uid(self) -> str:
        if self.product_id:
            return f"product:{self.product_id}"
        return f"text:{self.description.strip().lower()}"


@dataclass
class Receipt:
    """In-store receipt (kassabon) summary."""

    id: str
    datetime: datetime | None
    total: float


@dataclass
class OrderLine:
    product_id: int
    title: str
    quantity: int


@dataclass
class Order:
    """Active online order (the basket)."""

    id: int
    state: str
    total: float
    discount: float
    delivery_date: str | None
    delivery_start: str | None
    delivery_end: str | None
    items: list[OrderLine] = field(default_factory=list)


@dataclass
class Fulfillment:
    """A submitted order awaiting delivery or pickup."""

    order_id: int
    status: str
    shopping_type: str
    modifiable: bool
    total: float
    date: str | None
    start_time: str | None
    end_time: str | None
    time_display: str | None


@dataclass
class BonusProduct:
    title: str
    mechanism: str
    price_now: float | None
    price_was: float | None
    product_id: int | None
    category: str | None


@dataclass
class BonusOverview:
    start_date: str | None
    end_date: str | None
    total_count: int
    spotlight: list[BonusProduct] = field(default_factory=list)


@dataclass
class Product:
    product_id: int
    title: str
    brand: str | None
    unit_size: str | None
    price: float | None
    is_bonus: bool
    bonus_mechanism: str | None


def extract_code(value: str) -> str:
    """Return the authorization code from a raw code or an appie://login-exit URL."""
    value = value.strip()
    if "code=" in value:
        query = urlparse(value).query or value.split("?", 1)[-1]
        codes = parse_qs(query).get("code")
        if codes and codes[0]:
            return codes[0]
    if not value or " " in value or "/" in value:
        raise ValueError("no authorization code found")
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _amount(obj: Any) -> float:
    if isinstance(obj, dict):
        return float(obj.get("amount") or 0)
    return float(obj or 0)


class AppieClient:
    """Minimal async client for the AH API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens | None = None,
        on_tokens_updated: Callable[[Tokens], Awaitable[None] | None] | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._on_tokens_updated = on_tokens_updated
        self._base_url = base_url
        self._refresh_lock = asyncio.Lock()
        # Sent as appie-current-order-id, mirroring the iOS app.
        self._order_id: int | None = None

    @property
    def tokens(self) -> Tokens | None:
        return self._tokens

    # Auth

    async def async_exchange_code(self, code: str) -> Tokens:
        """Exchange an authorization code for tokens."""
        data = await self._request(
            "POST",
            "/mobile-auth/v1/auth/token",
            json={"clientId": CLIENT_ID, "code": code},
            auth=False,
        )
        self._tokens = Tokens.from_response(data)
        await self._notify_tokens()
        return self._tokens

    async def async_refresh_token(self) -> Tokens:
        if not self._tokens or not self._tokens.refresh_token:
            raise AppieAuthError("no refresh token available")
        try:
            data = await self._request(
                "POST",
                "/mobile-auth/v1/auth/token/refresh",
                json={"clientId": CLIENT_ID, "refreshToken": self._tokens.refresh_token},
                auth=False,
            )
        except AppieError as err:
            raise AppieAuthError(f"token refresh failed: {err}") from err
        self._tokens = Tokens.from_response(data, member_id=self._tokens.member_id)
        await self._notify_tokens()
        return self._tokens

    async def _ensure_token(self) -> None:
        if not self._tokens:
            raise AppieAuthError("not authenticated")
        if not self._tokens.expired:
            return
        async with self._refresh_lock:
            if self._tokens.expired:
                await self.async_refresh_token()

    async def _notify_tokens(self) -> None:
        if self._on_tokens_updated and self._tokens:
            result = self._on_tokens_updated(self._tokens)
            if asyncio.iscoroutine(result):
                await result

    # HTTP

    def _headers(self, auth: bool) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "x-client-name": CLIENT_ID,
            "x-client-version": CLIENT_VERSION,
            "x-application": APPLICATION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if auth and self._tokens:
            headers["Authorization"] = f"Bearer {self._tokens.access_token}"
        if auth and self._order_id:
            headers["appie-current-order-id"] = str(self._order_id)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        auth: bool = True,
        _retry: bool = True,
    ) -> Any:
        if auth:
            await self._ensure_token()
        try:
            async with self._session.request(
                method,
                self._base_url + path,
                json=json,
                headers=self._headers(auth),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401 and auth and _retry:
                    await self.async_refresh_token()
                    return await self._request(method, path, json=json, auth=auth, _retry=False)
                if resp.status in (401, 403):
                    raise AppieAuthError(f"{resp.status} on {path}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise AppieError(f"{resp.status} on {path}: {text[:200]}", resp.status)
                if resp.status == 204:
                    return None
                text = await resp.text()
                if not text:
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AppieError(f"request to {path} failed: {err}") from err

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        data = await self._request("POST", "/graphql", json=body)
        if data and data.get("errors"):
            raise AppieError(f"graphql error: {data['errors'][0].get('message')}")
        return (data or {}).get("data") or {}

    # Shopping list (Mijn lijst)

    async def async_get_shopping_list(self) -> list[ShoppingListItem]:
        data = await self._request("GET", "/mobile-services/shoppinglist/v2/items")
        items: list[ShoppingListItem] = []
        for raw in (data or {}).get("items", []):
            description = raw.get("description") or (raw.get("vagueTermDetails") or {}).get(
                "searchTermValue", ""
            )
            items.append(
                ShoppingListItem(
                    description=description,
                    quantity=int(raw.get("quantity") or 1),
                    checked=bool(raw.get("strikedthrough", raw.get("strikeThrough", False))),
                    origin_code=raw.get("originCode") or "TXT",
                    product_id=raw.get("productId") or None,
                    position=raw.get("position"),
                    type=raw.get("type") or "SHOPPABLE",
                )
            )
        return items

    async def async_patch_shopping_list(self, items: list[ShoppingListItem]) -> None:
        """Upsert items on the shopping list. Quantity 0 removes an item."""
        payload = []
        for item in items:
            entry: dict[str, Any] = {
                "description": item.description,
                "quantity": item.quantity,
                "type": item.type,
                "originCode": item.origin_code,
                "strikeThrough": item.checked,
            }
            if item.product_id:
                entry["productId"] = item.product_id
                entry["searchTerm"] = item.description
            payload.append(entry)
        await self._request(
            "PATCH", "/mobile-services/shoppinglist/v2/items", json={"items": payload}
        )

    async def async_add_text_item(self, description: str, quantity: int = 1) -> None:
        await self.async_patch_shopping_list(
            [ShoppingListItem(description, max(quantity, 1), False, "TXT")]
        )

    async def async_add_product_item(self, product_id: int, title: str, quantity: int = 1) -> None:
        await self.async_patch_shopping_list(
            [ShoppingListItem(title, max(quantity, 1), False, "PRD", product_id=product_id)]
        )

    # Products

    async def async_search_products(self, query: str, limit: int = 10) -> list[Product]:
        params = urlencode({"query": query, "page": 0, "size": limit, "sortOn": "RELEVANCE"})
        data = await self._request("GET", f"/mobile-services/product/search/v2?{params}")
        products = []
        for raw in (data or {}).get("products", [])[:limit]:
            price = raw.get("currentPrice") or raw.get("priceBeforeBonus")
            products.append(
                Product(
                    product_id=int(raw.get("webshopId")),
                    title=raw.get("title", ""),
                    brand=raw.get("brand"),
                    unit_size=raw.get("salesUnitSize"),
                    price=float(price) if price is not None else None,
                    is_bonus=bool(raw.get("isBonus")),
                    bonus_mechanism=raw.get("bonusMechanism"),
                )
            )
        return products

    # Receipts

    async def async_get_receipts(self, limit: int = 100) -> list[Receipt]:
        data = await self._graphql(_RECEIPTS_QUERY, {"offset": 0, "limit": limit})
        raw = (data.get("posReceiptsPage") or {}).get("posReceipts") or []
        receipts = [
            Receipt(
                id=str(r.get("id")),
                datetime=_parse_datetime(r.get("dateTime")),
                total=_amount(r.get("totalAmount")),
            )
            for r in raw
        ]
        receipts.sort(key=lambda r: r.datetime or datetime.min, reverse=True)
        return receipts

    # Orders

    async def async_get_active_order(self) -> Order | None:
        try:
            data = await self._request(
                "GET", "/mobile-services/order/v1/summaries/active?sortBy=DEFAULT"
            )
        except AppieAuthError:
            raise
        except AppieError as err:
            if err.status == 404:
                return None
            raise
        if not data or not data.get("id"):
            return None
        self._order_id = int(data["id"])
        price = data.get("totalPrice") or {}
        delivery = data.get("deliveryInformation") or {}
        items = [
            OrderLine(
                product_id=int((op.get("product") or {}).get("webshopId") or 0),
                title=(op.get("product") or {}).get("title", ""),
                quantity=int(op.get("quantity") or 0),
            )
            for op in data.get("orderedProducts") or []
        ]
        return Order(
            id=int(data["id"]),
            state=data.get("state", ""),
            total=float(price.get("priceTotalPayable") or 0),
            discount=float(price.get("priceDiscount") or 0),
            delivery_date=delivery.get("deliveryDate"),
            delivery_start=delivery.get("deliveryStartTime"),
            delivery_end=delivery.get("deliveryEndTime"),
            items=items,
        )

    async def async_get_fulfillments(self) -> list[Fulfillment]:
        data = await self._graphql(_FULFILLMENTS_QUERY)
        result = (data.get("orderFulfillments") or {}).get("result") or []
        fulfillments = []
        for r in result:
            delivery = r.get("delivery") or {}
            slot = delivery.get("slot") or {}
            fulfillments.append(
                Fulfillment(
                    order_id=int(r.get("orderId") or 0),
                    status=r.get("statusDescription") or delivery.get("status") or "",
                    shopping_type=r.get("shoppingType") or "",
                    modifiable=bool(r.get("modifiable")),
                    total=_amount((r.get("totalPrice") or {}).get("totalPrice")),
                    date=slot.get("date"),
                    start_time=slot.get("startTime"),
                    end_time=slot.get("endTime"),
                    time_display=slot.get("timeDisplay"),
                )
            )
        fulfillments.sort(key=lambda f: (f.date or "9999", f.start_time or ""))
        return fulfillments

    async def async_update_order(self, items: dict[int, int]) -> None:
        """Set product quantities in the active order. Quantity 0 removes the product."""
        payload = [
            {
                "productId": pid,
                "quantity": qty,
                "originCode": "PRD",
                "description": "",
                "strikethrough": False,
            }
            for pid, qty in items.items()
        ]
        await self._request(
            "PUT", "/mobile-services/order/v1/items?sortBy=DEFAULT", json={"items": payload}
        )

    # Bonus

    async def async_get_bonus(self, today: date | None = None) -> BonusOverview:
        today = today or date.today()
        meta = await self._request("GET", "/mobile-services/bonuspage/v3/metadata") or {}
        start = end = None
        total = 0
        for period in meta.get("periods") or []:
            p_start, p_end = period.get("bonusStartDate"), period.get("bonusEndDate")
            if p_start and p_end and not (p_start <= today.isoformat() <= p_end):
                continue
            start, end = p_start, p_end
            for tab in period.get("tabs") or []:
                for url_meta in tab.get("urlMetadataList") or []:
                    if url_meta.get("bonusType") == "NATIONAL":
                        total += int(url_meta.get("count") or 0)
            break

        params = urlencode({"application": APPLICATION, "date": today.isoformat()})
        section = await self._request(
            "GET", f"/mobile-services/bonuspage/v2/section/spotlight?{params}"
        ) or {}
        spotlight: list[BonusProduct] = []
        for entry in section.get("bonusGroupOrProducts") or []:
            if product := entry.get("product"):
                spotlight.append(
                    BonusProduct(
                        title=product.get("title", ""),
                        mechanism=product.get("bonusMechanism") or "",
                        price_now=product.get("currentPrice"),
                        price_was=product.get("priceBeforeBonus"),
                        product_id=product.get("webshopId"),
                        category=product.get("mainCategory"),
                    )
                )
            elif group := entry.get("bonusGroup"):
                spotlight.append(
                    BonusProduct(
                        title=group.get("segmentDescription", ""),
                        mechanism=group.get("discountDescription") or "",
                        price_now=group.get("exampleForPrice"),
                        price_was=group.get("exampleFromPrice"),
                        product_id=None,
                        category=group.get("category"),
                    )
                )
        return BonusOverview(start_date=start, end_date=end, total_count=total, spotlight=spotlight)
