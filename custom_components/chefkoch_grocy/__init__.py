"""Chefkoch → Grocy: import chefkoch.de recipes into Grocy (recipe only)."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .chefkoch import ChefkochError, async_fetch_image, async_fetch_recipe
from .const import (
    ATTR_ENTRY_ID,
    ATTR_EXISTING,
    ATTR_PICTURE,
    ATTR_SERVINGS,
    ATTR_URL,
    DEFAULT_IMPORT_PICTURE,
    DOMAIN,
    GROCY_RECIPE_PICTURE_GROUP,
    EXISTING_OPTIONS,
    EXISTING_OVERWRITE,
    EXISTING_SKIP,
    FRONTEND_URL,
    SERVICE_IMPORT_RECIPE,
    VERSION,
)
from .grocy import GrocyAuthError, GrocyClient, GrocyConnectionError, GrocyError
from .parser import Recipe, is_chefkoch_url, to_grocy_description

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = []

# Only config entries are supported; this keeps hassfest happy about async_setup.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_URL): cv.string,
        vol.Optional(ATTR_EXISTING, default=EXISTING_SKIP): vol.In(EXISTING_OPTIONS),
        vol.Optional(ATTR_PICTURE): cv.boolean,
        vol.Optional(ATTR_SERVINGS): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

_UMAP = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ẞ": "SS"}
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass(slots=True)
class RuntimeData:
    """Per config entry runtime data."""

    client: GrocyClient
    entry_id: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chefkoch → Grocy from a config entry."""
    client = GrocyClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY]
    )

    try:
        version = await client.async_get_version()
    except GrocyAuthError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except GrocyConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except GrocyError as err:
        raise ConfigEntryNotReady(str(err)) from err

    _LOGGER.debug("Verbunden mit Grocy %s unter %s", version or "?", entry.data[CONF_URL])

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = RuntimeData(
        client=client, entry_id=entry.entry_id
    )

    await _async_register_services(hass)
    await _async_register_frontend(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #


async def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_RECIPE):
        return

    async def _handle_import(call: ServiceCall) -> ServiceResponse:
        return await _async_handle_import(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_RECIPE,
        _handle_import,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _get_runtime(hass: HomeAssistant, entry_id: str | None) -> RuntimeData:
    runtimes: dict[str, RuntimeData] = hass.data.get(DOMAIN) or {}
    if not runtimes:
        raise ServiceValidationError(
            "Die Integration 'Chefkoch → Grocy' ist nicht eingerichtet."
        )
    if entry_id:
        runtime = runtimes.get(str(entry_id))
        if runtime is None:
            raise ServiceValidationError(f"Unbekannte Grocy-Instanz: {entry_id}")
        return runtime
    if len(runtimes) > 1:
        raise ServiceValidationError(
            "Es sind mehrere Grocy-Instanzen eingerichtet – bitte 'entry_id' angeben."
        )
    return next(iter(runtimes.values()))


async def _async_handle_import(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    runtime = _get_runtime(hass, call.data.get(ATTR_ENTRY_ID))
    session = async_get_clientsession(hass)

    urls = [part for part in re.split(r"[\s,]+", str(call.data[ATTR_URL]).strip()) if part]
    if not urls:
        raise ServiceValidationError("Bitte mindestens eine Chefkoch-URL angeben.")

    existing = call.data.get(ATTR_EXISTING, EXISTING_SKIP)
    picture = call.data.get(ATTR_PICTURE)
    picture = DEFAULT_IMPORT_PICTURE if picture is None else bool(picture)
    servings = call.data.get(ATTR_SERVINGS)

    results: list[dict[str, Any]] = []
    for url in urls:
        result: dict[str, Any] = {"url": url}
        try:
            if not is_chefkoch_url(url):
                raise ChefkochError("Das ist keine chefkoch.de-URL.")
            recipe = await async_fetch_recipe(session, url)
            if servings:
                recipe.servings = int(servings)
            result.update(
                await _async_import_recipe(
                    runtime.client, session, recipe, existing=existing, picture=picture
                )
            )
        except (ChefkochError, GrocyError) as err:
            _LOGGER.warning("Import von %s fehlgeschlagen: %s", url, err)
            result["error"] = str(err)
        results.append(result)

    if results and all("error" in result for result in results):
        raise ServiceValidationError(results[0]["error"])

    imported = [result for result in results if "error" not in result]
    _LOGGER.debug(
        "%s von %s Rezept(en) importiert", len(imported), len(results)
    )
    return {"results": results}


async def _async_import_recipe(
    client: GrocyClient,
    session: Any,
    recipe: Recipe,
    *,
    existing: str,
    picture: bool,
) -> dict[str, Any]:
    """Create/update the Grocy recipe and return a result summary."""
    payload: dict[str, Any] = {
        "name": recipe.name,
        "description": to_grocy_description(recipe),
        "base_servings": recipe.servings,
        "desired_servings": recipe.servings,
        # No products/recipe positions are created, so Grocy must not ask for
        # missing ingredients on the shopping list.
        "not_check_shoppinglist": 1,
        "type": "normal",
    }

    match = await _async_find_recipe(client, recipe.name)

    if match is not None and existing == EXISTING_SKIP:
        return {
            "name": recipe.name,
            "recipe_id": int(match["id"]),
            "action": "skipped",
        }

    if match is not None and existing == EXISTING_OVERWRITE:
        recipe_id = int(match["id"])
        await client.async_update_recipe(recipe_id, payload)
        action = "updated"
    else:
        recipe_id = await client.async_create_recipe(payload)
        action = "created"

    if picture and recipe.image_url:
        try:
            await _async_attach_picture(client, session, recipe_id, recipe)
        except GrocyError as err:
            _LOGGER.warning(
                "Rezeptbild für '%s' konnte nicht übernommen werden: %s", recipe.name, err
            )

    return {
        "name": recipe.name,
        "recipe_id": recipe_id,
        "action": action,
        "servings": recipe.servings,
        "ingredients": len(recipe.ingredients),
        "steps": len(recipe.instructions),
    }


async def _async_find_recipe(client: GrocyClient, name: str) -> dict[str, Any] | None:
    target = " ".join(name.split()).casefold()
    for item in await client.async_get_recipes():
        if " ".join(str(item.get("name") or "").split()).casefold() == target:
            return item
    return None


def _picture_file_name(name: str, content_type: str) -> str:
    slug = "".join(_UMAP.get(char, char) for char in name)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()[:80] or "rezept"
    return f"{slug}{_IMAGE_EXTENSIONS.get(content_type, '.jpg')}"


async def _async_attach_picture(
    client: GrocyClient, session: Any, recipe_id: int, recipe: Recipe
) -> None:
    if not recipe.image_url:
        return
    image = await async_fetch_image(session, recipe.image_url)
    if not image:
        return
    content, content_type = image
    file_name = _picture_file_name(recipe.name, content_type)
    await client.async_upload_file(
        GROCY_RECIPE_PICTURE_GROUP, file_name, content, content_type
    )
    await client.async_update_recipe(recipe_id, {"picture_file_name": file_name})


# --------------------------------------------------------------------------- #
# Lovelace card
# --------------------------------------------------------------------------- #

_FRONTEND_FLAG = "chefkoch_grocy_frontend_registered"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the Lovelace card before any config entry is set up."""
    await _async_register_frontend(hass)
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and register the bundled Lovelace card."""
    if hass.data.get(_FRONTEND_FLAG):
        return

    card_path = str(Path(__file__).parent / "frontend" / "chefkoch-grocy-card.js")
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL, card_path, cache_headers=False)]
        )
        add_extra_js_url(hass, f"{FRONTEND_URL}?v={VERSION}")
    except Exception:  # noqa: BLE001 - the card is optional, never break setup
        _LOGGER.exception("Die Lovelace-Karte konnte nicht registriert werden")
    else:
        hass.data[_FRONTEND_FLAG] = True
