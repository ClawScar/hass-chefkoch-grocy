"""Minimal asynchronous client for the Grocy REST API."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import REQUEST_TIMEOUT


class GrocyError(Exception):
    """Base error for Grocy requests."""


class GrocyAuthError(GrocyError):
    """Raised when Grocy rejects the API key."""


class GrocyConnectionError(GrocyError):
    """Raised when Grocy cannot be reached."""


class GrocyClient:
    """Talks to the Grocy API with an API key."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_key: str,
        *,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self._session = session
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = {"GROCY-API-KEY": self._api_key, "Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                f"{self.base_url}/api{path}",
                json=json_body,
                data=data,
                headers=request_headers,
                timeout=self._timeout,
            ) as response:
                if response.status in (401, 403):
                    raise GrocyAuthError(
                        f"Grocy hat den API-Schlüssel abgelehnt (HTTP {response.status})."
                    )
                if response.status >= 400:
                    body = (await response.text())[:300].strip()
                    raise GrocyError(f"Grocy-Fehler (HTTP {response.status}): {body}")
                if response.status == 204:
                    return None
                content_type = response.headers.get("Content-Type", "")
                if "json" in content_type:
                    return await response.json(content_type=None)
                return await response.text()
        except aiohttp.ClientError as err:
            raise GrocyConnectionError(f"Verbindung zu Grocy fehlgeschlagen: {err}") from err
        except TimeoutError as err:
            raise GrocyConnectionError("Zeitüberschreitung bei der Verbindung zu Grocy.") from err

    async def async_get_version(self) -> str | None:
        """Return the Grocy version, raises on connection/auth problems."""
        info = await self._request("GET", "/system/info") or {}
        version = info.get("grocy_version") if isinstance(info, dict) else None
        if isinstance(version, dict):
            return version.get("Version") or version.get("version")
        if isinstance(version, str):
            return version
        return None

    async def async_get_recipes(self) -> list[dict[str, Any]]:
        """Return all recipes (used for duplicate detection)."""
        data = await self._request("GET", "/objects/recipes")
        return data if isinstance(data, list) else []

    async def async_create_recipe(self, payload: dict[str, Any]) -> int:
        """Create a recipe and return its id."""
        data = await self._request("POST", "/objects/recipes", json_body=payload) or {}
        recipe_id = data.get("created_object_id") if isinstance(data, dict) else None
        if recipe_id is None:
            raise GrocyError("Grocy hat keine Rezept-ID zurückgegeben.")
        return int(recipe_id)

    async def async_update_recipe(self, recipe_id: int, fields: dict[str, Any]) -> None:
        """Update fields of an existing recipe."""
        await self._request("PUT", f"/objects/recipes/{recipe_id}", json_body=fields)

    async def async_upload_file(
        self, group: str, file_name: str, content: bytes, content_type: str
    ) -> None:
        """Upload a file into one of Grocy's storage groups (e.g. ``recipes``)."""
        encoded_name = quote(base64.b64encode(file_name.encode("utf-8")).decode("ascii"), safe="")
        await self._request(
            "PUT",
            f"/files/{group}/{encoded_name}",
            data=content,
            headers={"Content-Type": content_type},
        )
