"""Shopping list (Mijn lijst) as a Home Assistant to-do list."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import AppieError, ShoppingListItem
from .coordinator import AppieConfigEntry, AppieCoordinator
from .entity import AppieEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AppieShoppingList(entry.runtime_data.coordinator, entry)])


def _summary(item: ShoppingListItem) -> str:
    if item.quantity > 1:
        return f"{item.quantity}x {item.description}"
    return item.description


def _parse_summary(summary: str) -> tuple[int, str]:
    """Parse '3x melk' into (3, 'melk')."""
    head, _, rest = summary.strip().partition(" ")
    if rest and head[:-1].isdigit() and head[-1].lower() == "x":
        return max(int(head[:-1]), 1), rest.strip()
    return 1, summary.strip()


class AppieShoppingList(AppieEntity, TodoListEntity):
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: AppieCoordinator, entry: AppieConfigEntry) -> None:
        super().__init__(coordinator, entry, "shopping_list")

    def _items_by_uid(self) -> dict[str, ShoppingListItem]:
        if not self.coordinator.data:
            return {}
        return {item.uid: item for item in self.coordinator.data.shopping_list}

    @property
    def todo_items(self) -> list[TodoItem] | None:
        if not self.coordinator.data:
            return None
        return [
            TodoItem(
                uid=item.uid,
                summary=_summary(item),
                status=TodoItemStatus.COMPLETED if item.checked else TodoItemStatus.NEEDS_ACTION,
            )
            for item in self.coordinator.data.shopping_list
        ]

    async def _patch(self, items: list[ShoppingListItem]) -> None:
        try:
            await self.coordinator.client.async_patch_shopping_list(items)
        except AppieError as err:
            raise HomeAssistantError(f"Updating shopping list failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        quantity, description = _parse_summary(item.summary or "")
        if not description:
            raise HomeAssistantError("Item needs a description")
        await self._patch([ShoppingListItem(description, quantity, False, "TXT")])

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._items_by_uid().get(item.uid or "")
        if current is None:
            raise HomeAssistantError(f"Item {item.uid} not found")
        checked = item.status == TodoItemStatus.COMPLETED
        quantity, description = _parse_summary(item.summary or _summary(current))
        if current.product_id or description == current.description:
            # Product items keep their AH title; only quantity and status change.
            await self._patch([replace(current, quantity=quantity, checked=checked)])
            return
        # Renaming a free-text item: remove the old entry and add the new one.
        await self._patch(
            [
                replace(current, quantity=0),
                ShoppingListItem(description, quantity, checked, "TXT"),
            ]
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        items = self._items_by_uid()
        to_delete = [replace(items[uid], quantity=0) for uid in uids if uid in items]
        if to_delete:
            await self._patch(to_delete)
