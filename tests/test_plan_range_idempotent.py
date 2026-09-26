"""Regression (V9-MP1): plan_range darf ohne echte Planaenderung KEINE neue
Einkaufsliste erzeugen.

Hintergrund: GET /dashboard (von life-ops gepollt) ruft plan_range auf. Frueher
lief auto_refresh() bedingungslos und schloss+erzeugte bei JEDEM Poll eine neue
ShoppingList (Wurzel des I5-Runaways, 119.921 Listen). Der Fix macht auto_refresh
abhaengig von einer query-basierten Plan-Signatur: unveraenderter Plan =>
unveraenderte Liste => kein Row-Churn.
"""

from datetime import date

from sqlalchemy import func, select

from app.models import Ingredient, Recipe, RecipeIngredient, ShoppingList
from app.services.planning import PlanningService


class _FakeKalender:
    """Kalender-Stub ohne Netz: plan_range nutzt nur needs_packed_lunch."""

    def needs_packed_lunch(self, _d: date) -> bool:
        return False

    def get_day_type(self, _d: date) -> str:
        return "frei"

    def get_day_types_range(self, _d: date, _days: int) -> dict:
        return {}


def _shopping_list_count(db) -> int:
    return db.execute(select(func.count()).select_from(ShoppingList)).scalar() or 0


def test_plan_range_ohne_aenderung_erzeugt_keine_neue_einkaufsliste(db, mock_lager):
    # Minimales, planbares Setup: ein Rezept mit reichlich Bestand.
    ing = Ingredient(name_canonical="Reis", default_unit="g", lager_product_id=10)
    db.add(ing)
    db.flush()
    mock_lager.set_stock(10, "g", 1_000_000)

    recipe = Recipe(name="Reis pur", cook_time_min=10)
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing.id, amount=50, unit="g"))
    db.flush()

    svc = PlanningService(db, mock_lager, _FakeKalender())
    today = date.today()

    # 1. Lauf: plant das Board + erzeugt (mind.) eine Einkaufsliste.
    svc.plan_range(today, 1)
    n_after_first = _shopping_list_count(db)
    assert n_after_first >= 1, "erster plan_range-Lauf sollte eine Einkaufsliste erzeugen"

    # 2. Lauf: identischer Zustand, nichts zu planen -> KEINE neue Liste (der Fix).
    svc.plan_range(today, 1)
    n_after_second = _shopping_list_count(db)

    assert n_after_second == n_after_first, (
        "plan_range darf ohne Planaenderung keine neue Einkaufsliste erzeugen "
        f"(nach 1x: {n_after_first}, nach 2x: {n_after_second}), auto_refresh-Guard defekt"
    )


def test_range_plan_fingerprint_reagiert_auf_planaenderung(db, mock_lager):
    # Fingerprint muss sich aendern, wenn ein Slot einen Recipe zugewiesen bekommt.
    recipe = Recipe(name="X", cook_time_min=5)
    db.add(recipe)
    db.flush()
    svc = PlanningService(db, mock_lager, _FakeKalender())
    today = date.today()

    fp_leer = svc._range_plan_fingerprint(today, 1)

    from app.models import MealSlot
    slot = MealSlot(date=today, slot_type="dinner", status="planned", planned_recipe_id=recipe.id)
    db.add(slot)
    db.flush()

    fp_geplant = svc._range_plan_fingerprint(today, 1)
    assert fp_leer != fp_geplant, "Fingerprint muss sich bei Slot-/Recipe-Aenderung aendern"
