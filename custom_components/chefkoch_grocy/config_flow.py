"""Config flow for Chefkoch → Grocy."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import DOMAIN
from .grocy import GrocyAuthError, GrocyClient, GrocyConnectionError, GrocyError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _normalize_url(value: str) -> str:
    url = str(value).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url


class ChefkochGrocyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Grocy URL and API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = _normalize_url(user_input[CONF_URL])
            api_key = str(user_input[CONF_API_KEY]).strip()

            client = GrocyClient(async_get_clientsession(self.hass), url, api_key)
            try:
                await client.async_get_version()
            except GrocyAuthError:
                errors["base"] = "invalid_auth"
            except GrocyConnectionError:
                errors["base"] = "cannot_connect"
            except GrocyError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unerwarteter Fehler beim Verbindungstest")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                host = urlparse(url).hostname or url
                return self.async_create_entry(
                    title=f"Grocy ({host})",
                    data={CONF_URL: url, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
