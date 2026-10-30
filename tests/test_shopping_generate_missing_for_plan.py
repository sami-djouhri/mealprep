"""Test: ShoppingService includes missing ingredients with MISSING_FOR_PLAN (via MockLager)."""

from datetime import date, timedelta

from app.models import (
    Ingredient,
    MealSlot,
    Recipe,
    RecipeIngredient,
)
from app.services.shopping import ShoppingService


def test_shopping_generates_missing_for_plan(db, mock_lager):
    today = date.today()

    # Ingredients with lager_product_ids
    ing_reis = Ingredient(name_canonical="Reis", default_unit="g", lager_product_id=10)
    ing_haehnchen = Ingredient(name_canonical="Haehnchenbrust", default_unit="g", lager_product_id=20)
    db.add_all([ing_reis, ing_haehnchen])
    db.flush()

    # Mock Lager stock: plenty of Reis, NO Haehnchenbrust
    mock_lager.set_stock(10, "g", 1000)
    # product 20 not set -> defaults to 0.0

    # Recipe needing both
    recipe = Recipe(name="Chicken Rice", cook_time_min=25)
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing_reis.id, amount=100, unit="g"))
    db.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing_haehnchen.id, amount=200, unit="g"))
    db.flush()

    # Plan a slot with this recipe
    slot = MealSlot(
        date=today, slot_type="dinner", status="planned",
        planned_recipe_id=recipe.id,
    )
    db.add(slot)
    db.flush()

    svc = ShoppingService(db, lager=mock_lager)
    sl = svc.generate_for_window(today, days_ahead=1)

    assert sl is not None
    assert len(sl.lines) >= 1

    # Find the Haehnchenbrust line
    haehnchen_lines = [l for l in sl.lines if l.ingredient_id == ing_haehnchen.id]
    assert len(haehnchen_lines) == 1, f"Expected 1 line for Haehnchen, got {len(haehnchen_lines)}"

    line = haehnchen_lines[0]
    assert line.needed_amount >= 200
    assert "MISSING_FOR_PLAN" in line.reason_codes

    # Reis should NOT appear (enough in stock)
    reis_lines = [l for l in sl.lines if l.ingredient_id == ing_reis.id]
    assert len(reis_lines) == 0, "Reis should not be on shopping list (enough stock)"
