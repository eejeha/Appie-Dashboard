"""The AH shopping list as a to-do list."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AppieError
from .coordinator import AppieConfigEntry, ListCoordinator
from .entity import device_info
from .models import ORIGIN_TEXT, ListItem, new_product_item, new_text_item, text_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AppieShoppingList(entry)])


class AppieShoppingList(CoordinatorEntity[ListCoordinator], TodoListEntity):
    """Two-way synced AH shopping list."""

    _attr_has_entity_name = True
    _attr_name = "Boodschappenlijst"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, entry: AppieConfigEntry) -> None:
        super().__init__(entry.runtime_data.shopping_list)
        self._attr_unique_id = f"{entry.unique_id}_boodschappenlijst"
        self._attr_device_info = device_info(entry)

    @property
    def _items(self) -> dict[str, ListItem]:
        return {i.key: i for i in self.coordinator.data or []}

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_todo_items = [_to_todo(i) for i in self.coordinator.data or []]
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        text = (item.summary or "").strip()
        if not text:
            return
        # A bare number is an AH product id (webshopId), as in the app's links.
        new = new_product_item(int(text)) if text.isdigit() else new_text_item(text)
        existing = self._items.get(new.key)
        if existing:
            # Already on the list (maybe ticked off): put it back as open.
            await self._patch([existing.patch(checked=False)])
        else:
            await self._patch([new.patch()])

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._items.get(item.uid or "")
        if current is None:
            raise HomeAssistantError(f"Item {item.uid} staat niet (meer) op de lijst")
        checked = item.status == TodoItemStatus.COMPLETED
        summary = (item.summary or "").strip()
        if current.origin == ORIGIN_TEXT and summary and text_key(summary) != current.key.split("#")[0]:
            # Free text is keyed on its text: renaming = remove + add.
            renamed = new_text_item(summary)
            renamed.quantity, renamed.checked = current.quantity, checked
            await self._patch([current.patch(quantity=0), renamed.patch()])
        elif checked != current.checked:
            await self._patch([current.patch(checked=checked)])

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        items = self._items
        await self._patch([items[uid].patch(quantity=0) for uid in uids if uid in items])

    async def _patch(self, body: list[dict]) -> None:
        if not body:
            return
        try:
            await self.coordinator.client.patch_list(body)
        except AppieError as err:
            raise HomeAssistantError(f"Albert Heijn: {err}") from err
        await self.coordinator.async_refresh()


def _to_todo(item: ListItem) -> TodoItem:
    notes = []
    if item.quantity > 1:
        notes.append(f"{item.quantity} stuks")
    if item.is_bonus:
        notes.append(f"Bonus: {item.bonus_mechanism}" if item.bonus_mechanism else "Bonus")
    return TodoItem(
        summary=item.title,
        uid=item.key,
        status=TodoItemStatus.COMPLETED if item.checked else TodoItemStatus.NEEDS_ACTION,
        description=" · ".join(notes) or None,
    )
