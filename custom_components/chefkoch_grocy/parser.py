"""Turn a chefkoch.de HTML page into a :class:`Recipe`.

chefkoch.de embeds schema.org/Recipe data as JSON-LD, which is far more
reliable than scraping the rendered DOM.  This module deliberately uses the
standard library only, so the parsing can be tested without Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import html as html_lib
import json
import re
from typing import Any
from urllib.parse import urlparse

DEFAULT_SERVINGS = 4

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\u00a0]+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_JSONLD_RE = re.compile(
    r"""<script[^>]*type\s*=\s*["']application/ld\+json["'][^>]*>(?P<data>.*?)</script>""",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_NUMBER_RE = re.compile(r"(\d+)")
_DURATION_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", re.IGNORECASE)

_SCORED_KEYS = (
    "name",
    "description",
    "recipeIngredient",
    "recipeInstructions",
    "recipeYield",
    "image",
    "totalTime",
    "author",
)


class RecipeParseError(Exception):
    """Raised when a page does not contain usable recipe data."""


@dataclass(slots=True)
class Recipe:
    """A recipe as needed by Grocy."""

    name: str
    description: str = ""
    servings: int = DEFAULT_SERVINGS
    ingredients: list[str] = field(default_factory=list)
    # (section heading or None, step text)
    instructions: list[tuple[str | None, str]] = field(default_factory=list)
    total_time: str | None = None
    category: str | None = None
    keywords: list[str] = field(default_factory=list)
    image_url: str | None = None
    author: str | None = None
    source_url: str | None = None


def is_chefkoch_url(url: str) -> bool:
    """Return True for chefkoch.de URLs."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "chefkoch.de" or host.endswith(".chefkoch.de")


def format_duration(value: str | None) -> str | None:
    """Turn an ISO 8601 duration like ``PT1H30M`` into ``1 Std. 30 Min.``."""
    if not value:
        return None
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        return value.strip() or None
    days, hours, minutes = (int(group) if group else 0 for group in match.groups())
    parts: list[str] = []
    if days:
        parts.append(f"{days} Tag" + ("e" if days > 1 else ""))
    if hours:
        parts.append(f"{hours} Std.")
    if minutes:
        parts.append(f"{minutes} Min.")
    return " ".join(parts) or None


def _text(value: Any) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        return ""
    cleaned = html_lib.unescape(_TAG_RE.sub(" ", value))
    cleaned = cleaned.replace("\u00a0", " ").replace("\r", "")
    return _SPACE_RE.sub(" ", cleaned).strip()


def _text_list(value: Any) -> list[str]:
    """Normalise a schema.org text-or-list value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part for part in re.split(r"\r?\n", value)]
        if len(parts) == 1:
            text = _text(value)
            return [text] if text else []
        return [text for text in (_text(part) for part in parts) if text]
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_text_list(item))
        return result
    if isinstance(value, dict):
        for key in ("text", "name", "value", "url", "contentUrl"):
            if key in value:
                return _text_list(value[key])
    return []


def _types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    if isinstance(raw, str):
        return {raw.lower()}
    if isinstance(raw, (list, tuple)):
        return {str(item).lower() for item in raw}
    return set()


def _instructions(value: Any, section: str | None = None) -> list[tuple[str | None, str]]:
    """Normalise every legal shape of ``recipeInstructions`` into (section, step)."""
    result: list[tuple[str | None, str]] = []
    if isinstance(value, str):
        for block in re.split(r"\r?\n\s*\r?\n", value):
            text = _text(block)
            if text:
                result.append((section, text))
        return result
    if isinstance(value, (list, tuple)):
        for item in value:
            result.extend(_instructions(item, section))
        return result
    if isinstance(value, dict):
        types = _types(value)
        if "howtosection" in types or "itemlist" in types:
            name = _text(value.get("name")) if "howtosection" in types else ""
            children = value.get("itemListElement") or value.get("steps") or []
            result.extend(_instructions(children, name or section))
            return result
        for key in ("text", "name", "description"):
            if value.get(key):
                result.extend(_instructions(value[key], section))
                break
        return result
    return result


def _collect_recipe_nodes(data: Any) -> list[dict[str, Any]]:
    """Return every node of type Recipe, including nested ``@graph`` entries."""
    found: list[dict[str, Any]] = []
    stack: list[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "recipe" in _types(node):
                found.append(node)
            stack.extend(
                value for value in node.values() if isinstance(value, (dict, list))
            )
        elif isinstance(node, list):
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return found


def _score(node: dict[str, Any]) -> int:
    return sum(1 for key in _SCORED_KEYS if node.get(key))


def _image_url(value: Any) -> str | None:
    """Pick the largest image of the various image shapes."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        best: str | None = None
        best_width = -1
        for item in value:
            url = _image_url(item)
            if not url:
                continue
            width = 0
            if isinstance(item, dict):
                try:
                    width = int(item.get("width") or 0)
                except (TypeError, ValueError):
                    width = 0
            if width > best_width:
                best, best_width = url, width
        return best
    if isinstance(value, dict):
        for key in ("url", "contentUrl", "@id"):
            if key in value:
                return _image_url(value[key])
    return None


def _servings(value: Any) -> int | None:
    """Extract a serving count from ``4 Portionen``, ``[4]`` or a QuantitativeValue."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        count = int(value)
        return count if 0 < count <= 100 else None
    if isinstance(value, (list, tuple)):
        for item in value:
            number = _servings(item)
            if number:
                return number
        return None
    if isinstance(value, dict):
        for key in ("value", "maxValue", "minValue", "unitText", "name"):
            if key in value:
                number = _servings(value[key])
                if number:
                    return number
        return None
    if isinstance(value, str):
        match = _NUMBER_RE.search(value)
        if match:
            count = int(match.group(1))
            if 0 < count <= 100:
                return count
    return None


def _first(value: Any) -> str | None:
    for item in _text_list(value):
        return item
    return None


def _fallback_name(page: str) -> str:
    match = _TITLE_RE.search(page or "")
    if not match:
        return ""
    title = _text(match.group("title"))
    return title.split("|")[0].strip()


def _load_json_ld(page: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for match in _JSONLD_RE.finditer(page or ""):
        raw = match.group("data").strip()
        if not raw:
            continue
        data: Any = None
        for candidate in (raw, _CONTROL_RE.sub("", raw)):
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if data is None:
            continue
        nodes.extend(_collect_recipe_nodes(data))
    return nodes


def parse_recipe_html(page: str, url: str | None = None) -> Recipe:
    """Parse a chefkoch.de recipe page into a :class:`Recipe`."""
    nodes = _load_json_ld(page)
    if not nodes:
        raise RecipeParseError(
            "Auf dieser Seite wurden keine Rezeptdaten (schema.org/Recipe) gefunden. "
            "Zeigt der Link wirklich auf ein einzelnes Rezept?"
        )
    node = max(nodes, key=_score)

    name = _text(node.get("name")) or _fallback_name(page)
    if not name:
        raise RecipeParseError("Das Rezept hat keinen Namen.")

    keywords: list[str] = []
    for entry in _text_list(node.get("keywords")):
        for keyword in entry.split(","):
            keyword = keyword.strip()
            if keyword and keyword not in keywords:
                keywords.append(keyword)

    return Recipe(
        name=name,
        description=_text(node.get("description")),
        servings=_servings(node.get("recipeYield")) or DEFAULT_SERVINGS,
        ingredients=_text_list(node.get("recipeIngredient")),
        instructions=_instructions(node.get("recipeInstructions")),
        total_time=format_duration(_text(node.get("totalTime")) or None),
        category=_first(node.get("recipeCategory")),
        keywords=keywords,
        image_url=_image_url(node.get("image")),
        author=_first(node.get("author")),
        source_url=url,
    )


def to_grocy_description(recipe: Recipe) -> str:
    """Build the Grocy recipe description (Markdown) from a parsed recipe."""
    blocks: list[str] = []

    if recipe.description:
        blocks.append(recipe.description)

    meta: list[str] = []
    if recipe.total_time:
        meta.append(f"**Zeit:** {recipe.total_time}")
    if recipe.servings:
        meta.append(f"**Portionen:** {recipe.servings}")
    if recipe.category:
        meta.append(f"**Kategorie:** {recipe.category}")
    if recipe.author:
        meta.append(f"**Autor:** {recipe.author}")
    if recipe.source_url:
        meta.append(f"**Quelle:** [chefkoch.de]({recipe.source_url})")
    if meta:
        blocks.append("  \n".join(meta))

    if recipe.ingredients:
        lines = [f"## Zutaten ({recipe.servings} Portionen)"]
        lines.extend(f"- {ingredient}" for ingredient in recipe.ingredients)
        blocks.append("\n".join(lines))

    if recipe.instructions:
        lines = ["## Zubereitung"]
        current_section: str | None = None
        number = 0
        for section, text in recipe.instructions:
            if section and section != current_section:
                lines.append("")
                lines.append(f"**{section}**")
                lines.append("")
                current_section = section
            number += 1
            lines.append(f"{number}. {text}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks).strip()
