"""Constants for the Chefkoch → Grocy integration."""

from __future__ import annotations

DOMAIN = "chefkoch_grocy"
NAME = "Chefkoch → Grocy"
VERSION = "1.0.6"

CONF_URL = "url"
CONF_API_KEY = "api_key"

SERVICE_IMPORT_RECIPE = "import_recipe"

ATTR_URL = "url"
ATTR_EXISTING = "existing"
ATTR_PICTURE = "picture"
ATTR_SERVINGS = "servings"
ATTR_ENTRY_ID = "entry_id"

EXISTING_SKIP = "skip"
EXISTING_OVERWRITE = "overwrite"
EXISTING_CREATE = "create"
EXISTING_OPTIONS = [EXISTING_SKIP, EXISTING_OVERWRITE, EXISTING_CREATE]

DEFAULT_IMPORT_PICTURE = True
# Grocy serves recipe pictures from this storage group (data/storage/recipepictures).
GROCY_RECIPE_PICTURE_GROUP = "recipepictures"
REQUEST_TIMEOUT = 25

FRONTEND_URL = "/chefkoch_grocy/chefkoch-grocy-card.js"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
