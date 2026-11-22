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

# chefkoch.de appends promotional sentences to the JSON-LD description, e.g.
# "Über 1684 Bewertungen und für sehr gut befunden. Mit ► Portionsrechner …".
_PROMO_MARKERS = (
    "bewertungen",
    "für sehr gut befunden",
    "portionsrechner",
    "kochbuch",
    "video-tipps",
    "►",
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
    difficulty: str | None = None
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


def _clean_description(text: str) -> str:
    """Drop the promotional sentences chefkoch.de appends to the description."""
    if not text:
        return ""
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if any(marker in sentence.casefold() for marker in _PROMO_MARKERS):
            continue
        kept.append(sentence)
    return " ".join(kept)


def _strip_author(name: str, author: str | None) -> str:
    """Remove ``von <author>`` (the recipe's creator) from the title."""
    if not name:
        return name
    if author:
        stripped = re.sub(
            rf"\s+von\s+{re.escape(author)}\s*$", "", name, flags=re.IGNORECASE
        )
        if stripped != name:
            return stripped.strip()

    # Without an author field, only strip a trailing "von Firstname Lastname".
    return re.sub(
        r"\s+von\s+[A-ZÄÖÜ][\wäöüß.\-]*(?:\s+[A-ZÄÖÜ][\wäöüß.\-]*){1,2}\s*$",
        "",
        name,
    ).strip()


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

    author = _first(node.get("author"))
    name = _text(node.get("name")) or _fallback_name(page)
    name = _strip_author(name, author)
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
        description=_clean_description(_text(node.get("description"))),
        servings=_servings(node.get("recipeYield")) or DEFAULT_SERVINGS,
        ingredients=_text_list(node.get("recipeIngredient")),
        instructions=_instructions(node.get("recipeInstructions")),
        total_time=format_duration(_text(node.get("totalTime")) or None),
        difficulty=_first(node.get("difficulty")),
        category=_first(node.get("recipeCategory")),
        keywords=keywords,
        image_url=_image_url(node.get("image")),
        author=author,
        source_url=url,
    )


def to_grocy_description(recipe: Recipe) -> str:
    """Build the Grocy recipe description (HTML) from a parsed recipe.

    Grocy renders the description as HTML, so headings, lists and the info
    block stay readable instead of showing raw Markdown characters.
    """
    lines: list[str] = ['<div class="container">']
    lines.append(f"  <h1>{html_lib.escape(recipe.name)}</h1>")

    info: list[str] = []
    if recipe.servings:
        info.append(f"  <strong>Portionen:</strong> {recipe.servings}<br>")
    if recipe.total_time:
        info.append(f"  <strong>Gesamtzeit:</strong> {html_lib.escape(recipe.total_time)}<br>")
    if recipe.difficulty:
        info.append(
            f"  <strong>Schwierigkeit:</strong> {html_lib.escape(recipe.difficulty)}<br>"
        )
    if info:
        lines.append('  <div class="info">')
        lines.extend(info)
        lines.append("  </div>")

    if recipe.description:
        lines.append(f"  <p>{html_lib.escape(recipe.description)}</p>")

    if recipe.ingredients:
        lines.append("")
        lines.append("  <h2>Zutaten</h2>")
        lines.append("  <ul>")
        lines.extend(f"    <li>{html_lib.escape(item)}</li>" for item in recipe.ingredients)
        lines.append("  </ul>")

    if recipe.instructions:
        lines.append("")
        lines.append("  <h2>Zubereitung</h2>")
        current_section: str | None = None
        list_open = False
        for section, text in recipe.instructions:
            if section and section != current_section:
                if list_open:
                    lines.append("  </ol>")
                lines.append(f"  <h3>{html_lib.escape(section)}</h3>")
                lines.append("  <ol>")
                list_open = True
                current_section = section
            elif not list_open:
                lines.append("  <ol>")
                list_open = True
            lines.append(f"    <li>{html_lib.escape(text)}</li>")
        if list_open:
            lines.append("  </ol>")

    if recipe.source_url:
        link = html_lib.escape(recipe.source_url, quote=True)
        lines.append("")
        lines.append(
            f'  <p><small>Quelle: <a href="{link}">chefkoch.de</a></small></p>'
        )

    lines.append("</div>")
    return "\n".join(lines)
