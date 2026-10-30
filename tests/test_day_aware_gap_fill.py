"""Tests for day-aware cumulative macro gap-fill scoring."""

from datetime import date, timedelta

from app.models import (
    GoalPhase,
    Ingredient,
    MealSlot,
    Recipe,
    RecipeIngredient,
    UserProfile,
)
from app.schemas import DailyMacroTargets, DayNutritionContext, NutritionInfo
from app.services.meal_decision import MealDecisionEngine
from app.services.profile import ProfileService


def test_profile_derive_daily_targets_cut(db):
    """ProfileService derives targets for weight-loss goal (target < current)."""
    profile = UserProfile(
        id=1, height_cm=180, weight_kg=80, sex="male",
        activity_level="moderate", target_weight_kg=75.0,
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    targets = svc.derive_daily_targets(profile)

    # Weight-loss: protein 2.2 g/kg, fat 0.9 g/kg
    assert targets.protein_g == round(80 * 2.2, 1)
    assert targets.fat_g == round(80 * 0.9, 1)
    assert targets.fiber_g == 30.0
    # kcal = TDEE - 500
    assert targets.kcal > 0


def test_profile_derive_daily_targets_maintain(db):
    """ProfileService derives targets when no weight goal (maintain)."""
    profile = UserProfile(
        id=1, height_cm=175, weight_kg=75, sex="male",
        activity_level="moderate",
    )
    db.add(profile)
    db.flush()

    svc = ProfileService(db)
    targets = svc.derive_daily_targets(profile)

    # Maintain: protein 1.8 g/kg, fat 0.8 g/kg
    assert targets.protein_g == round(75 * 1.8, 1)
    assert targets.fat_g == round(75 * 0.8, 1)


def test_gap_score_favors_protein_when_carbs_already_high(db, mock_lager):
    """After a carb-heavy breakfast, protein-rich lunch should score higher on macro gap."""
    today = date.today()

    # Ingredients with lager_product_id
    ing_chicken = Ingredient(name_canonical="Haehnchen", default_unit="g", lager_product_id=1)
    ing_reis = Ingredient(name_canonical="Reis", default_unit="g", lager_product_id=2)
    db.add_all([ing_chicken, ing_reis])
    db.flush()

    # Mock Lager stock
    mock_lager.set_stock(1, "g", 500)
    mock_lager.set_stock(2, "g", 1000)

    # Recipe A: high protein, low carbs (like chicken + veggies)
    recipe_protein = Recipe(name="Chicken Bowl", cook_time_min=20)
    recipe_protein.nutrition_per_portion = {
        "kcal": 400, "protein_g": 45, "carbs_g": 10, "fat_g": 15, "fiber_g": 3,
    }
    db.add(recipe_protein)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe_protein.id,
                            ingredient_id=ing_chicken.id, amount=200, unit="g"))

    # Recipe B: high carbs, low protein (like plain rice)
    recipe_carbs = Recipe(name="Reis pur", cook_time_min=20)
    recipe_carbs.nutrition_per_portion = {
        "kcal": 400, "protein_g": 8, "carbs_g": 85, "fat_g": 2, "fiber_g": 1,
    }
    db.add(recipe_carbs)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe_carbs.id,
                            ingredient_id=ing_reis.id, amount=120, unit="g"))
    db.flush()

    # Simulate: after carb-heavy breakfast, lots of protein still needed
    targets = DailyMacroTargets(
        kcal=2400, protein_g=160, carbs_g=280, fat_g=64, fiber_g=30,
    )
    day_ctx = DayNutritionContext(
        targets=targets,
        planned_so_far=NutritionInfo(
            kcal=500, protein_g=10, carbs_g=90, fat_g=5, fiber_g=3,
        ),
        slot_count_total=3,
        slot_index=1,  # lunch = second slot
    )

    slot = MealSlot(date=today, slot_type="lunch", status="planned")
    db.add(slot)
    db.flush()

    engine = MealDecisionEngine(db, lager=mock_lager)

    # Score both recipes with the day context
    gap_protein = engine._macro_gap_score(recipe_protein, day_ctx)
    gap_carbs = engine._macro_gap_score(recipe_carbs, day_ctx)

    assert gap_protein > gap_carbs, (
        f"Protein-rich recipe should score higher when protein is the gap: "
        f"{gap_protein:.3f} vs {gap_carbs:.3f}"
    )


def test_backwards_compat_no_context(db, mock_lager):
    """Engine without day_context should work exactly as before (legacy scoring)."""
    today = date.today()

    ing = Ingredient(name_canonical="Skyr", default_unit="g", lager_product_id=10)
    db.add(ing)
    db.flush()

    mock_lager.set_stock(10, "g", 500)

    recipe = Recipe(name="Skyr Bowl", cook_time_min=5)
    recipe.nutrition_per_portion = {"kcal": 220, "protein_g": 33, "carbs_g": 16, "fat_g": 1, "fiber_g": 0}
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing.id,
                            amount=300, unit="g"))
    db.flush()

    slot = MealSlot(date=today, slot_type="breakfast", status="planned")
    db.add(slot)
    db.flush()

    engine = MealDecisionEngine(db, lager=mock_lager)
    # Call without day_context (legacy path)
    result = engine.decide_best_for_slot(slot, phase=None, day_context=None)

    assert result is not None
    assert result.selected_recipe_id == recipe.id
    # variety should be 0.5 (neutral) when no context is passed
    bd = result.score_breakdown[str(recipe.id)]
    assert bd.variety == 0.5


def test_day_nutrition_context_accumulation():
    """DayNutritionContext should track remaining macros correctly after add_planned."""
    targets = DailyMacroTargets(
        kcal=2400, protein_g=160, carbs_g=280, fat_g=64, fiber_g=30,
    )
    ctx = DayNutritionContext(targets=targets, slot_count_total=3, slot_index=0)

    # Initially, remaining == targets
    rem = ctx.remaining
    assert rem.kcal == 2400
    assert rem.protein_g == 160

    # Plan a meal
    ctx.add_planned({"kcal": 500, "protein_g": 40, "carbs_g": 60, "fat_g": 15, "fiber_g": 5})

    assert ctx.slot_index == 1
    assert ctx.slots_left == 2
    rem = ctx.remaining
    assert rem.kcal == 1900
    assert rem.protein_g == 120
    assert rem.carbs_g == 220
    assert rem.fat_g == 49
    assert rem.fiber_g == 25

    # Plan another meal
    ctx.add_planned({"kcal": 800, "protein_g": 50, "carbs_g": 100, "fat_g": 20, "fiber_g": 10})

    assert ctx.slot_index == 2
    assert ctx.slots_left == 1
    rem = ctx.remaining
    assert rem.kcal == 1100
    assert rem.protein_g == 70
    assert rem.carbs_g == 120
    assert rem.fat_g == 29
    assert rem.fiber_g == 15
