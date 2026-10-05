"""Constants for the Albert Heijn integration."""

from datetime import timedelta

DOMAIN = "appie"

API_BASE = "https://api.ah.nl"
LOGIN_URL = (
    "https://login.ah.nl/login?client_id=appie-ios"
    "&response_type=code&redirect_uri=appie://login-exit"
)
CLIENT_ID = "appie-ios"
CLIENT_VERSION = "9.28"
APPLICATION = "AHWEBSHOP"
USER_AGENT = f"Appie/{CLIENT_VERSION} (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

# Refresh the 7-day access token once less than this is left.
TOKEN_REFRESH_MARGIN = timedelta(days=1)

LIST_INTERVAL = timedelta(seconds=60)
BONUS_INTERVAL = timedelta(hours=6)
RECEIPTS_INTERVAL = timedelta(hours=1)
FAVORITES_INTERVAL = timedelta(hours=12)

# How many receipts to fetch per update (covers well over a month).
RECEIPTS_PAGE_SIZE = 50

# "Vaak gekocht" buttons: how many, counted over how many days of receipts.
FAVORITES_COUNT = 10
FAVORITES_DAYS = 120
