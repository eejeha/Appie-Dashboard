"""Constants for the Albert Heijn (Appie) integration."""

from datetime import timedelta

DOMAIN = "appie"

CONF_CODE = "code"
CONF_TOKENS = "tokens"

DATA_UPDATE_INTERVAL = timedelta(minutes=15)
BONUS_UPDATE_INTERVAL = timedelta(hours=6)

SERVICE_ADD_TO_ORDER = "add_to_order"
SERVICE_REMOVE_FROM_ORDER = "remove_from_order"
SERVICE_SHOPPING_LIST_TO_ORDER = "shopping_list_to_order"
SERVICE_SEARCH_PRODUCTS = "search_products"
SERVICE_ADD_PRODUCT_TO_LIST = "add_product_to_list"

ATTR_PRODUCT_ID = "product_id"
ATTR_QUANTITY = "quantity"
ATTR_QUERY = "query"
ATTR_LIMIT = "limit"
ATTR_TITLE = "title"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
