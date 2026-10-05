"""Tests for setup, sensors, to-do list, services and config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.appie.api import AppieAuthError, AppieError, ShoppingListItem, Tokens
from custom_components.appie.const import CONF_TOKENS, DOMAIN
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(hass, config_entry, mock_client):
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.albert_heijn_open_shopping_list_items").state == "1"
    assert hass.states.get("sensor.albert_heijn_spent_this_month").state == "19.75"
    assert hass.states.get("sensor.albert_heijn_last_receipt").state == "12.5"
    assert hass.states.get("sensor.albert_heijn_order_total").state == "30.0"
    assert hass.states.get("sensor.albert_heijn_bonus_offers").state == "321"
    delivery = hass.states.get("sensor.albert_heijn_next_delivery")
    expected = dt_util.as_utc(dt_util.parse_datetime("2026-10-06T18:00").replace(tzinfo=dt_util.get_default_time_zone()))
    assert delivery.state == expected.isoformat()
    assert delivery.attributes["time_window"] == "18:00 - 20:00"
    assert hass.states.get("todo.albert_heijn_shopping_list").state == "1"


async def test_setup_auth_failure_starts_reauth(hass, config_entry, mock_client):
    mock_client.async_get_shopping_list.side_effect = AppieAuthError("401")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert flows and flows[0]["context"]["source"] == "reauth"


async def test_optional_parts_do_not_fail_setup(hass, config_entry, mock_client):
    mock_client.async_get_receipts.side_effect = AppieError("500")
    mock_client.async_get_bonus.side_effect = AppieError("500")
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.albert_heijn_spent_this_month").state == "0"


async def test_todo_operations(hass, config_entry, mock_client):
    await _setup(hass, config_entry)
    entity = "todo.albert_heijn_shopping_list"

    await hass.services.async_call("todo", "add_item", {"item": "3x eieren"}, target={"entity_id": entity}, blocking=True)
    assert mock_client.async_patch_shopping_list.await_args.args[0] == [ShoppingListItem("eieren", 3, False, "TXT")]

    await hass.services.async_call("todo", "update_item", {"item": "text:melk", "status": "completed"}, target={"entity_id": entity}, blocking=True)
    assert mock_client.async_patch_shopping_list.await_args.args[0] == [ShoppingListItem("melk", 2, True, "TXT")]

    await hass.services.async_call("todo", "update_item", {"item": "text:melk", "rename": "karnemelk"}, target={"entity_id": entity}, blocking=True)
    assert mock_client.async_patch_shopping_list.await_args.args[0] == [
        ShoppingListItem("melk", 0, False, "TXT"),
        ShoppingListItem("karnemelk", 1, False, "TXT"),
    ]

    await hass.services.async_call("todo", "remove_item", {"item": "product:482500"}, target={"entity_id": entity}, blocking=True)
    assert mock_client.async_patch_shopping_list.await_args.args[0] == [
        ShoppingListItem("AH Woksaus", 0, True, "PRD", product_id=482500)
    ]


async def test_order_services(hass, config_entry, mock_client):
    await _setup(hass, config_entry)

    await hass.services.async_call(DOMAIN, "add_to_order", {"product_id": 482500, "quantity": 1}, blocking=True)
    mock_client.async_update_order.assert_awaited_with({482500: 3})

    await hass.services.async_call(DOMAIN, "remove_from_order", {"product_id": 482500}, blocking=True)
    mock_client.async_update_order.assert_awaited_with({482500: 0})

    mock_client.async_get_shopping_list.return_value = [
        ShoppingListItem("melk", 1, False, "TXT"),
        ShoppingListItem("AH Woksaus", 2, False, "PRD", product_id=482500),
        ShoppingListItem("Kaas", 1, True, "PRD", product_id=1),
    ]
    result = await hass.services.async_call(DOMAIN, "shopping_list_to_order", {}, blocking=True, return_response=True)
    mock_client.async_update_order.assert_awaited_with({482500: 4})
    assert result == {"added": 1, "skipped_text_items": ["melk"]}


async def test_config_flow(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert "login.ah.nl" in result["description_placeholders"]["login_url"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "appie://login-exit?state=1"})
    assert result["errors"] == {"code": "invalid_code"}

    with patch(
        "custom_components.appie.config_flow.AppieClient.async_exchange_code",
        AsyncMock(side_effect=AppieError("400")),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "abc"})
    assert result["errors"] == {"base": "auth_failed"}

    tokens = Tokens("a", "r", 0, "999")
    with patch(
        "custom_components.appie.config_flow.AppieClient.async_exchange_code",
        AsyncMock(return_value=tokens),
    ), patch("custom_components.appie.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "appie://login-exit?code=abc"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "999"
    assert result["data"] == {CONF_TOKENS: tokens.as_dict()}


async def test_reauth_flow(hass, config_entry, mock_client):
    await _setup(hass, config_entry)
    result = await config_entry.start_reauth_flow(hass)
    tokens = Tokens("new", "r", 0, "12345")
    with patch(
        "custom_components.appie.config_flow.AppieClient.async_exchange_code",
        AsyncMock(return_value=tokens),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "abc"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKENS]["access_token"] == "new"
