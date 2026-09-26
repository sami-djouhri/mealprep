"""Stock forecast: calculate how many days of food are in the house."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, RecipeIngredient
from app.schemas import DaysOfFoodResult
from app.services.lager_adapter import LagerAdapter

log = logging.getLogger(__name__)


def calculate_days_of_food(
    db: Session,
    lager: LagerAdapter,
) -> DaysOfFoodResult:
    """Estimate how many days of food are available based on Lager stock.

    For each ingredient with a lager_product_id that appears in any recipe:
      - available = lager.get_available(product_id, unit)
      - avg_daily = lager.get_turnover(product_id).avg_daily
      - days = available / avg_daily (if avg_daily > 0)

    Returns min(days) across all tracked ingredients.

    ★★ Jeder Rueckgabeweg sagt mit ``belastbar``, ob die Zahl etwas taugt.
    Bis zum 2026-09-13 gaben vier verschiedene Lagen dieselbe ``0`` zurueck:
    lager nicht angebunden, nichts verknuepft, lager nicht erreichbar, und
    keine Verbrauchsdaten. Nur die letzte hat mit dem Vorrat zu tun, und keine
    der vier heisst "das Essen ist alle". Das Dashboard zeigte trotzdem einen
    roten Balken.

    Zwei Sammelabrufe statt zweier Aufrufe je Zutat. Der Grund steht in
    ``LagerAdapter.verbrauchsraten``: die Schleife lief in den Anfragedeckel
    von lager, und der Adapter machte aus dem 429 eine Null.
    """
    if not lager.available:
        return DaysOfFoodResult(
            days=0,
            limiting_ingredient=None,
            grund="Lager ist nicht angebunden.",
        )

    # Get all ingredients that are linked to Lager and used in recipes
    linked = list(
        db.execute(
            select(Ingredient).where(
                Ingredient.lager_product_id.isnot(None),
                Ingredient.id.in_(
                    select(RecipeIngredient.ingredient_id).distinct()
                ),
            )
        ).scalars().all()
    )

    if not linked:
        return DaysOfFoodResult(
            days=0,
            limiting_ingredient=None,
            grund="Keine Zutat ist mit einem Lager-Produkt verknuepft.",
        )

    # ★ Zwei Schnappschuesse statt zweier Aufrufe je Zutat. Beide melden mit
    # False, wenn sie nichts holen konnten, und beides ist ein Grund, hier
    # nicht weiterzurechnen: ein Ausfall wird sonst zu einer Null, und eine
    # Null steht danach als Messwert im Dashboard.
    bestand_da = lager.schnappschuss_laden()
    raten_da = lager.raten_laden()
    if not bestand_da or not raten_da:
        fehlt = "Bestand" if not bestand_da else "Verbrauchsraten"
        return DaysOfFoodResult(
            days=0,
            limiting_ingredient=None,
            grund=f"Lager hat nicht geantwortet ({fehlt}).",
        )

    min_days = float("inf")
    limiting = None
    details = []

    for ing in linked:
        available = lager.get_available(ing.lager_product_id, ing.default_unit)
        turnover = lager.get_turnover(ing.lager_product_id)
        avg_daily = turnover.get("avg_daily", 0)

        if avg_daily <= 0:
            # No turnover data: skip (don't let it be the bottleneck)
            details.append({
                "ingredient": ing.name_canonical,
                "available": available,
                "avg_daily": 0,
                "days": None,
                "note": "keine Verbrauchsdaten",
            })
            continue

        days = available / avg_daily
        details.append({
            "ingredient": ing.name_canonical,
            "available": round(available, 1),
            "avg_daily": round(avg_daily, 2),
            "days": round(days, 1),
        })

        if days < min_days:
            min_days = days
            limiting = ing.name_canonical

    if min_days == float("inf"):
        # Gemessen, aber keine einzige Zutat hat Verbrauchsdaten. Das ist eine
        # Auskunft ueber die Datenlage, keine ueber den Vorrat.
        return DaysOfFoodResult(
            days=0,
            limiting_ingredient=None,
            details=details,
            grund=(
                "Keine der verknuepften Zutaten hat Verbrauchsdaten im "
                "Zeitraum. Der Vorrat laesst sich daraus nicht hochrechnen."
            ),
        )

    return DaysOfFoodResult(
        days=round(min_days, 1),
        limiting_ingredient=limiting,
        details=details,
        belastbar=True,
    )
