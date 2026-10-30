"""Test: MealDecisionEngine prefers recipes using expiring ingredients (via MockLager)."""

from datetime import date, timedelta

from app.models import (
    GoalPhase,
    Ingredient,
    MealSlot,
    Recipe,
    RecipeIngredient,
)
from app.services.meal_decision import MealDecisionEngine


def test_prefers_recipe_with_expiring_ingredients(db, mock_lager):
    today = date.today()

    # Two ingredients with lager_product_ids
    ing_exp = Ingredient(name_canonical="Skyr", default_unit="g", lager_product_id=100)
    ing_stable = Ingredient(name_canonical="Reis", default_unit="g", lager_product_id=200)
    db.add_all([ing_exp, ing_stable])
    db.flush()

    # Mock Lager: Skyr and Reis both available
    mock_lager.set_stock(100, "g", 500)
    mock_lager.set_stock(200, "g", 1000)

    # Mark Skyr as expiring soon
    mock_lager.set_expiring([
        {"product_id": 100, "product_name": "Skyr", "quantity": 500, "unit": "g",
         "mhd": str(today + timedelta(days=2)), "days_left": 2, "urgency": "kritisch"},
    ])

    # Recipe A: uses expiring Skyr
    recipe_a = Recipe(name="Skyr Bowl", cook_time_min=5)
    recipe_a.nutrition_per_portion = {"kcal": 220, "protein_g": 33, "carbs_g": 16, "fat_g": 1, "fiber_g": 0}
    db.add(recipe_a)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe_a.id, ingredient_id=ing_exp.id, amount=200, unit="g"))

    # Recipe B: uses only stable Reis (similar macros for fairness)
    recipe_b = Recipe(name="Reis pur", cook_time_min=20)
    recipe_b.nutrition_per_portion = {"kcal": 350, "protein_g": 7, "carbs_g": 78, "fat_g": 1, "fiber_g": 1}
    db.add(recipe_b)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe_b.id, ingredient_id=ing_stable.id, amount=100, unit="g"))

    db.flush()

    # Goal phase with MHD weight boosted
    phase = GoalPhase(name="Test", start_date=today, is_active=True)
    phase.scoring_weights = {"w_macro": 0.20, "w_mhd": 0.50, "w_eff": 0.20, "w_slot": 0.10}
    db.add(phase)
    db.flush()

    slot = MealSlot(date=today, slot_type="lunch", status="planned")
    db.add(slot)
    db.flush()

    engine = MealDecisionEngine(db, lager=mock_lager)
    result = engine.decide_best_for_slot(slot, phase)

    assert result is not None
    assert result.selected_recipe_id == recipe_a.id, (
        f"Expected recipe A (Skyr Bowl, ID {recipe_a.id}), "
        f"got ID {result.selected_recipe_id}"
    )
    # Verify the expiry score is higher for recipe A
    bd_a = result.score_breakdown[str(recipe_a.id)]
    bd_b = result.score_breakdown[str(recipe_b.id)]
    assert bd_a.expiry_util > bd_b.expiry_util
