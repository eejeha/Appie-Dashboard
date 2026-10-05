"""Tests for the response parsing (synthetic data in the shape AH returns)."""

import importlib.util
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location(
    "appie_models", Path(__file__).parents[1] / "custom_components/appie/models.py"
)
models = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = models
_spec.loader.exec_module(models)

IMG = [
    {"width": 800, "height": 800, "url": "https://img.invalid/800"},
    {"width": 400, "height": 400, "url": "https://img.invalid/400"},
    {"width": 200, "height": 200, "url": "https://img.invalid/200"},
    {"width": 48, "height": 48, "url": "https://img.invalid/48"},
]

LIST = {
    "id": "list-1",
    "items": [
        {
            "listItemId": 0, "strikedthrough": False, "quantity": 1, "type": "SHOPPABLE",
            "originCode": "PRD", "position": 1,
            "productDetails": {"product": {
                "webshopId": 111, "title": "AH Roomboter", "isBonus": False, "images": IMG,
            }},
        },
        {
            "listItemId": 0, "strikedthrough": False, "quantity": 2, "type": "SHOPPABLE",
            "originCode": "PRD", "position": 2,
            "productDetails": {"product": {
                "webshopId": 222, "title": "AH Courgette", "isBonus": True,
                "bonusMechanism": "2 voor 1.19",
            }},
        },
        {
            "listItemId": 0, "strikedthrough": True, "quantity": 1, "description": "Melk",
            "type": "SHOPPABLE", "originCode": "TXT",
            "vagueTermDetails": {"searchTermValue": "Melk", "bonus": False},
        },
        {
            "listItemId": 0, "strikedthrough": False, "quantity": 1, "description": "melk ",
            "type": "SHOPPABLE", "originCode": "TXT",
            "vagueTermDetails": {"searchTermValue": "melk", "bonus": False},
        },
    ],
}

PERSONAL = {
    "sectionType": "PO",
    "bonusGroupOrProducts": [
        {"bonusGroup": {
            "id": "g1", "segmentId": 900, "segmentDescription": "AH Pindakaas", "discountDescription": "15% KORTING",
            "exampleForPrice": 3.14, "exampleFromPrice": 3.69, "bonusEndDate": "2026-10-11",
            "activationStatus": "ACTIVATED", "images": IMG, "products": [],
        }},
        {"product": {
            "webshopId": 333, "title": "AH Tomaten", "bonusMechanism": "15% KORTING", "currentPrice": 2.54,
            "priceBeforeBonus": 2.99, "bonusEndDate": "2026-10-11", "activationStatus": "ASSIGNED",
        }},
    ],
}

PREVIOUS = {
    "sectionType": "PBO",
    "bonusGroupOrProducts": [
        {"product": {"webshopId": 333, "title": "AH Tomaten", "bonusMechanism": "15% KORTING"}},
        {"product": {"webshopId": 444, "title": "AH Druiven", "bonusMechanism": "2 voor 3.49"}},
    ],
}

RECEIPTS = {"data": {"posReceiptsPage": {"posReceipts": [
    {"id": "r2", "dateTime": "2026-10-04T15:00:00", "totalAmount": {"amount": 36.16}},
    {"id": "r1", "dateTime": "2026-10-03T09:00:00", "totalAmount": {"amount": 6.92}},
    {"id": "r0", "dateTime": "2026-09-30T18:00:00", "totalAmount": {"amount": 50.0}},
]}}}

DETAIL = {"data": {"posReceiptDetails": {
    "id": "r2",
    "products": [
        {"id": 1, "quantity": 1, "name": "BIO BANAAN", "price": {"amount": 2.39}, "amount": {"amount": 1.2}},
        {"id": 2, "quantity": 2, "name": "AH Melk", "price": None, "amount": {"amount": 2.58}},
    ],
    "discounts": [{"name": "BONUS", "amount": {"amount": -0.14}}, {"name": "X", "amount": {"amount": -0.56}}],
    "payments": [{"method": "PINNEN", "amount": {"amount": 36.16}}],
}}}


def test_parse_list():
    items = models.parse_list(LIST)
    assert [i.key for i in items] == ["product:111", "product:222", "text:melk", "text:melk#2"]
    butter, courgette, milk, milk2 = items
    assert butter.image == "https://img.invalid/200"
    assert courgette.quantity == 2 and courgette.is_bonus and courgette.bonus_mechanism == "2 voor 1.19"
    assert milk.checked and milk.origin == "TXT" and milk.product_id is None
    assert not milk2.checked


def test_patch_bodies():
    butter, _, milk, _ = models.parse_list(LIST)
    assert butter.patch(checked=True) == {
        "description": "AH Roomboter", "searchTerm": "AH Roomboter", "type": "SHOPPABLE",
        "originCode": "PRD", "quantity": 1, "strikeThrough": True, "productId": 111,
    }
    body = milk.patch(quantity=0)
    assert body["quantity"] == 0 and body["originCode"] == "TXT" and "productId" not in body
    assert models.new_text_item("  Kaas ").patch()["description"] == "Kaas"
    assert models.new_product_item(555).patch()["productId"] == 555


def test_relevant_bonus_order_and_dedupe():
    items = models.parse_list(LIST)
    personal = models.parse_bonus_section(PERSONAL, models.SOURCE_PERSONAL)
    previous = models.parse_bonus_section(PREVIOUS, models.SOURCE_PREVIOUS)
    offers = models.relevant_bonus(personal, previous, items)
    keys = [o.key for o in offers]
    # Courgette is on the list and on bonus but in neither section: first, from the list.
    assert keys[0] == "product:222" and offers[0].source == models.SOURCE_LIST and offers[0].on_list
    # Tomatoes are in both sections: kept once, as personal.
    assert keys.count("product:333") == 1
    assert next(o for o in offers if o.key == "product:333").source == models.SOURCE_PERSONAL
    assert keys[-1] == "product:444"
    group = next(o for o in offers if o.key == "group:900")
    assert group.activated is True and group.price == 3.14 and group.price_was == 3.69
    assert "product_ids" not in group.as_dict()


def test_on_list_flag_ignores_checked_items():
    items = models.parse_list(LIST)
    previous = models.parse_bonus_section(
        {"bonusGroupOrProducts": [{"product": {"webshopId": 111, "title": "AH Roomboter", "bonusMechanism": "1+1"}}]},
        models.SOURCE_PREVIOUS,
    )
    assert models.relevant_bonus([], previous, items)[0].on_list
    items[0].checked = True
    assert not next(o for o in models.relevant_bonus([], previous, items) if o.key == "product:111").on_list


def test_bonus_period():
    assert models.bonus_period({"periods": [{"bonusStartDate": "2026-10-05", "bonusEndDate": "2026-10-11"}]}) == (
        "2026-10-05", "2026-10-11")
    assert models.bonus_period({}) == (None, None)


def test_receipts():
    receipts = models.parse_receipts(RECEIPTS)
    assert [r.id for r in receipts] == ["r2", "r1", "r0"]
    assert models.month_total(receipts, date(2026, 10, 5)) == 43.08
    # 30 Sept 23:30 UTC is already 1 October in Amsterdam.
    late = models.parse_receipts({"data": {"posReceiptsPage": {"posReceipts": [
        {"id": "x", "dateTime": "2026-09-30T23:30:00.000Z", "totalAmount": {"amount": 10.0}}]}}})
    ams = ZoneInfo("Europe/Amsterdam")
    assert late[0].day(ams) == date(2026, 10, 1)
    assert models.month_total(late, date(2026, 10, 2), ams) == 10.0
    detail = models.parse_receipt_detail(DETAIL)
    assert detail.items[0] == {"name": "Bio banaan", "quantity": 1, "amount": 1.2}
    assert detail.items[1]["name"] == "AH Melk"
    assert models.pos_name("AH ELSTAR") == "AH elstar"
    assert models.pos_name("AHORNSIROOP") == "Ahornsiroop"
    assert detail.discount_total == -0.7
    assert detail.payments == ["PINNEN"]


def _lines(*rows):
    return [list(r) for r in rows]


def test_rank_purchases_counts_receipts_not_quantity():
    receipts = [
        _lines((1, "BIO BANAAN", 1, 1.2), (2, "KAISER WIT", 6, 1.7), (9, "STATIEGELD", 1, 0.15)),
        _lines((1, "BIO BANAAN", 1, 1.2), (3, "AH MELK", 1, 1.1)),
        _lines((1, "BIO BANAAN", 2, 2.4), (3, "AH MELK", 1, 1.1), (4, "BONUS", 1, -0.5)),
    ]
    ranked = models.rank_purchases(receipts)
    assert [r[0] for r in ranked] == [1, 3, 2]  # 3 receipts, 2 receipts, 1 receipt (6 pieces)
    assert ranked[0] == (1, "BIO BANAAN", 3)


def test_build_favorites_falls_back_to_text_and_dedupes():
    ranked = [(1, "BIO BANAAN", 14), (2, "AH PINDAKAAS", 14), (3, "AH PINDAKAAS GROOT", 3), (4, "AH THEE", 13)]
    webshop = {1: -1, 2: 123432, 3: 123432, 4: 106661}
    products = {
        123432: {"webshopId": 123432, "title": "AH Smeuige pindakaas", "isBonus": True,
                 "bonusMechanism": "15% KORTING", "images": IMG},
        106661: {"webshopId": 106661, "title": "AH Kruiden kamille"},
    }
    favs = models.build_favorites(ranked, webshop, products, limit=10)
    assert [f.title for f in favs] == ["Bio banaan", "AH Smeuige pindakaas", "AH Kruiden kamille"]
    assert [f.rank for f in favs] == [1, 2, 3]
    assert favs[0].product_id is None and favs[0].as_list_item().key == "text:bio banaan"
    assert favs[1].as_list_item().patch()["productId"] == 123432
    assert favs[1].is_bonus and favs[1].image == "https://img.invalid/200"
    assert len(models.build_favorites(ranked, webshop, products, limit=2)) == 2


def test_receipt_lines():
    assert models.receipt_lines(DETAIL) == [[1, "BIO BANAAN", 1, 1.2], [2, "AH Melk", 2, 2.58]]
