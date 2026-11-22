"""Downloading recipes and pictures from chefkoch.de."""

from __future__ import annotations

import aiohttp

from .const import REQUEST_TIMEOUT, USER_AGENT
from .parser import Recipe, RecipeParseError, parse_recipe_html

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

IMAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
}


class ChefkochError(Exception):
    """Raised when a chefkoch.de page cannot be fetched or parsed."""


async def async_fetch_recipe(
    session: aiohttp.ClientSession, url: str, *, timeout: int = REQUEST_TIMEOUT
) -> Recipe:
    """Fetch a chefkoch.de recipe page and parse it."""
    try:
        async with session.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as response:
            if response.status in (401, 403):
                raise ChefkochError(
                    "Chefkoch hat den Abruf abgelehnt (HTTP 403). Das passiert bei "
                    "VPN-/Rechenzentrums-IPs oder wenn sehr viele Anfragen gestellt "
                    "werden. Bitte aus dem Heimnetz erneut versuchen."
                )
            if response.status == 404:
                raise ChefkochError("Das Rezept existiert nicht (HTTP 404).")
            if response.status >= 400:
                raise ChefkochError(f"Chefkoch antwortete mit HTTP {response.status}.")
            page = await response.text()
    except aiohttp.ClientError as err:
        raise ChefkochError(f"Chefkoch-Seite konnte nicht geladen werden: {err}") from err
    except TimeoutError as err:
        raise ChefkochError("Zeitüberschreitung beim Laden der Chefkoch-Seite.") from err

    try:
        return parse_recipe_html(page, url)
    except RecipeParseError as err:
        raise ChefkochError(str(err)) from err


async def async_fetch_image(
    session: aiohttp.ClientSession, url: str, *, timeout: int = REQUEST_TIMEOUT
) -> tuple[bytes, str] | None:
    """Download a recipe picture; returns ``(content, content_type)`` or None."""
    try:
        async with session.get(
            url,
            headers=IMAGE_HEADERS,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as response:
            if response.status >= 400:
                return None
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                return None
            return await response.read(), content_type
    except (aiohttp.ClientError, TimeoutError):
        return None
