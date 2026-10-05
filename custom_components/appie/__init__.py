"""Albert Heijn (Appie) integration for Home Assistant."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import AppieAuthError, AppieClient, AppieError, Tokens
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_LIMIT,
    ATTR_PRODUCT_ID,
    ATTR_QUANTITY,
    ATTR_QUERY,
    ATTR_TITLE,
    CONF_TOKENS,
    DOMAIN,
    SERVICE_ADD_PRODUCT_TO_LIST,
    SERVICE_ADD_TO_ORDER,
    SERVICE_REMOVE_FROM_ORDER,
    SERVICE_SEARCH_PRODUCTS,
    SERVICE_SHOPPING_LIST_TO_ORDER,
)
from .coordinator import (
    AppieBonusCoordinator,
    AppieConfigEntry,
    AppieCoordinator,
    AppieRuntimeData,
)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_BASE_SCHEMA = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

ADD_TO_ORDER_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Required(ATTR_PRODUCT_ID): cv.positive_int,
        vol.Optional(ATTR_QUANTITY, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
    }
)
REMOVE_FROM_ORDER_SCHEMA = vol.Schema(
    {**_BASE_SCHEMA, vol.Required(ATTR_PRODUCT_ID): cv.positive_int}
)
LIST_TO_ORDER_SCHEMA = vol.Schema(_BASE_SCHEMA)
SEARCH_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Required(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_LIMIT, default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)
ADD_PRODUCT_TO_LIST_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Required(ATTR_PRODUCT_ID): cv.positive_int,
        vol.Required(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_QUANTITY, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    tokens = Tokens(**entry.data[CONF_TOKENS])

    @callback
    def _save_tokens(new_tokens: Tokens) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKENS: new_tokens.as_dict()}
        )

    client = AppieClient(async_get_clientsession(hass), tokens, on_tokens_updated=_save_tokens)

    coordinator = AppieCoordinator(hass, entry, client)
    bonus_coordinator = AppieBonusCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    try:
        await bonus_coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except ConfigEntryNotReady:
        # Bonus data is not essential; the coordinator retries on its own schedule.
        pass

    entry.runtime_data = AppieRuntimeData(client, coordinator, bonus_coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AppieConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> AppieConfigEntry:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError("No loaded Albert Heijn account found")
    if len(entries) > 1 and not entry_id:
        raise ServiceValidationError("Multiple accounts configured, pass config_entry_id")
    return entries[0]


def _register_services(hass: HomeAssistant) -> None:
    async def _run(call: ServiceCall, func):
        entry = _get_entry(hass, call)
        try:
            result = await func(entry.runtime_data)
        except AppieAuthError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError(f"Authentication failed: {err}") from err
        except AppieError as err:
            raise HomeAssistantError(str(err)) from err
        return result

    async def add_to_order(call: ServiceCall) -> None:
        async def _do(rt: AppieRuntimeData) -> None:
            pid = call.data[ATTR_PRODUCT_ID]
            current = 0
            if rt.coordinator.data and rt.coordinator.data.order:
                current = next(
                    (i.quantity for i in rt.coordinator.data.order.items if i.product_id == pid), 0
                )
            await rt.client.async_update_order({pid: current + call.data[ATTR_QUANTITY]})
            await rt.coordinator.async_request_refresh()

        await _run(call, _do)

    async def remove_from_order(call: ServiceCall) -> None:
        async def _do(rt: AppieRuntimeData) -> None:
            await rt.client.async_update_order({call.data[ATTR_PRODUCT_ID]: 0})
            await rt.coordinator.async_request_refresh()

        await _run(call, _do)

    async def shopping_list_to_order(call: ServiceCall) -> ServiceResponse:
        async def _do(rt: AppieRuntimeData) -> ServiceResponse:
            items = await rt.client.async_get_shopping_list()
            to_add: dict[int, int] = {}
            skipped: list[str] = []
            for item in items:
                if item.checked:
                    continue
                if item.product_id:
                    to_add[item.product_id] = to_add.get(item.product_id, 0) + item.quantity
                else:
                    skipped.append(item.description)
            order = rt.coordinator.data.order if rt.coordinator.data else None
            if order:
                for line in order.items:
                    if line.product_id in to_add:
                        to_add[line.product_id] += line.quantity
            if to_add:
                await rt.client.async_update_order(to_add)
                await rt.coordinator.async_request_refresh()
            return {"added": len(to_add), "skipped_text_items": skipped}

        return await _run(call, _do)

    async def search_products(call: ServiceCall) -> ServiceResponse:
        async def _do(rt: AppieRuntimeData) -> ServiceResponse:
            products = await rt.client.async_search_products(
                call.data[ATTR_QUERY], call.data[ATTR_LIMIT]
            )
            return {
                "products": [
                    {
                        "product_id": p.product_id,
                        "title": p.title,
                        "brand": p.brand,
                        "unit_size": p.unit_size,
                        "price": p.price,
                        "is_bonus": p.is_bonus,
                        "bonus_mechanism": p.bonus_mechanism,
                    }
                    for p in products
                ]
            }

        return await _run(call, _do)

    async def add_product_to_list(call: ServiceCall) -> None:
        async def _do(rt: AppieRuntimeData) -> None:
            await rt.client.async_add_product_item(
                call.data[ATTR_PRODUCT_ID], call.data[ATTR_TITLE], call.data[ATTR_QUANTITY]
            )
            await rt.coordinator.async_request_refresh()

        await _run(call, _do)

    hass.services.async_register(DOMAIN, SERVICE_ADD_TO_ORDER, add_to_order, ADD_TO_ORDER_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_FROM_ORDER, remove_from_order, REMOVE_FROM_ORDER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SHOPPING_LIST_TO_ORDER,
        shopping_list_to_order,
        LIST_TO_ORDER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_PRODUCTS,
        search_products,
        SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PRODUCT_TO_LIST, add_product_to_list, ADD_PRODUCT_TO_LIST_SCHEMA
    )
