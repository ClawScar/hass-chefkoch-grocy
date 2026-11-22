"""Tests for the pure chefkoch.de parser (no Home Assistant needed)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "chefkoch_grocy"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(COMPONENT))

import parser as ck  # noqa: E402


MINIMAL_PAGE = """
<html><head><title>Nudelsalat | Chefkoch</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Nudelsalat",
  "recipeYield": {"@type": "QuantitativeValue", "value": 6},
  "image": "https://img.chefkoch-cdn.de/nudelsalat.jpg",
  "recipeIngredient": "250 g Nudeln\\n1 Glas Mayonnaise",
  "recipeInstructions": "Nudeln kochen.\\n\\nAlles vermischen."
}
</script></head><body></body></html>
"""


class ParseChefkochPageTest(unittest.TestCase):
    def test_full_page_with_graph_and_sections(self) -> None:
        page = (FIXTURES / "chefkoch_kaesespaetzle.html").read_text(encoding="utf-8")
        recipe = ck.parse_recipe_html(page, "https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html")

        self.assertEqual(recipe.name, "Käsespätzle")
        self.assertEqual(
            recipe.description,
            "Klassische Käsespätzle wie bei Oma – einfach und cremig.",
        )
        self.assertEqual(recipe.servings, 4)
        self.assertEqual(len(recipe.ingredients), 3)
        self.assertEqual(recipe.ingredients[0], "500 g Mehl")
        self.assertEqual(recipe.total_time, "50 Min.")
        self.assertEqual(recipe.category, "Aufläufe")
        self.assertEqual(recipe.keywords, ["Käse", "Spätzle", "Vegetarisch"])
        self.assertEqual(recipe.author, "Oma Hilde")
        # the larger of the two images wins
        self.assertEqual(
            recipe.image_url, "https://img.chefkoch-cdn.de/recipes/15845/bilder/1/big.jpg"
        )

        self.assertEqual(len(recipe.instructions), 3)
        self.assertEqual(recipe.instructions[0][0], "Spätzle")
        self.assertEqual(
            recipe.instructions[0][1], "Mehl, Eier und Salz zu einem zähen Teig verkneten."
        )
        self.assertIsNone(recipe.instructions[2][0])

    def test_minimal_page_with_plain_instructions(self) -> None:
        recipe = ck.parse_recipe_html(MINIMAL_PAGE, "https://www.chefkoch.de/rezepte/1/Nudelsalat.html")

        self.assertEqual(recipe.name, "Nudelsalat")
        self.assertEqual(recipe.servings, 6)
        self.assertEqual(recipe.ingredients, ["250 g Nudeln", "1 Glas Mayonnaise"])
        self.assertEqual(
            [(None, "Nudeln kochen."), (None, "Alles vermischen.")], recipe.instructions
        )
        self.assertEqual(recipe.image_url, "https://img.chefkoch-cdn.de/nudelsalat.jpg")

    def test_page_without_recipe_data_raises(self) -> None:
        with self.assertRaises(ck.RecipeParseError):
            ck.parse_recipe_html("<html><body>Nichts</body></html>")

    def test_grocy_description_html(self) -> None:
        page = (FIXTURES / "chefkoch_kaesespaetzle.html").read_text(encoding="utf-8")
        recipe = ck.parse_recipe_html(page, "https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html")
        description = ck.to_grocy_description(recipe)

        self.assertTrue(description.startswith('<div class="container">'))
        self.assertTrue(description.endswith("</div>"))
        self.assertIn("<h1>Käsespätzle</h1>", description)
        self.assertIn("<strong>Portionen:</strong> 4", description)
        self.assertIn("<strong>Gesamtzeit:</strong> 50 Min.", description)
        self.assertIn("<h2>Zutaten</h2>", description)
        self.assertIn("<li>200 g Bergkäse, gerieben</li>", description)
        self.assertIn("<h2>Zubereitung</h2>", description)
        self.assertIn("<h3>Spätzle</h3>", description)
        self.assertIn("<li>Mehl, Eier und Salz zu einem zähen Teig verkneten.</li>", description)
        self.assertIn("<li>Schichten, mit Käse bestreuen und überbacken.</li>", description)
        self.assertIn(
            'Quelle: <a href="https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html">chefkoch.de</a>',
            description,
        )
        # no leftover Markdown syntax from the previous format
        self.assertNotIn("**", description)
        self.assertNotIn("## ", description)

    def test_grocy_description_escapes_html(self) -> None:
        recipe = ck.Recipe(name="A & B <script>", ingredients=["1 < 2 & 200 g Mehl"])
        description = ck.to_grocy_description(recipe)

        self.assertIn("<h1>A &amp; B &lt;script&gt;</h1>", description)
        self.assertIn("<li>1 &lt; 2 &amp; 200 g Mehl</li>", description)
        self.assertNotIn("<script>", description)

    def test_duration_formatting(self) -> None:
        self.assertEqual(ck.format_duration("PT1H30M"), "1 Std. 30 Min.")
        self.assertEqual(ck.format_duration("PT50M"), "50 Min.")
        self.assertEqual(ck.format_duration("PT2H"), "2 Std.")
        self.assertIsNone(ck.format_duration(None))

    def test_is_chefkoch_url(self) -> None:
        self.assertTrue(ck.is_chefkoch_url("https://www.chefkoch.de/rezepte/15845/Kaesespaetzle.html"))
        self.assertTrue(ck.is_chefkoch_url("https://chefkoch.de/x"))
        self.assertFalse(ck.is_chefkoch_url("https://example.com/chefkoch.de"))


if __name__ == "__main__":
    unittest.main()
