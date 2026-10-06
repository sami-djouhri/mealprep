"""SPA JSON API endpoints for the dashboard onepager."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func as sa_func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.domain import DomainError
from app.models import (
    GoalPhase,
    Ingredient,
    IntakeItem,
    MealSlot,
    Recipe,
    RecipeIngredient,
    ShoppingList,
    Supplement,
    SupplementLog,
)

log = logging.getLogger(__name__)
from app.schemas import (
    DashboardSlot,
    DashboardState,
    DayPlan,
    DayStats,
    DayStatus,
    DaysOfFoodResult,
    GoalContribution,
    IntakeLogOut,
    IntakeLogRequest,
    MissingIngredient,
    NextMealSuggestion,
    NutrientDeficit,
    NutritionInfo,
    ShoppingInfo,
    ShoppingLine,
    SlotRecipeInfo,
    StatsResponse,
    SupplementOut,
    SwapCandidateRecipe,
    SwapCandidatesResponse,
    DayNutritionContext,
)
from app.services.fitness_adapter import FitnessAdapter
from app.services.kalender_adapter import KalenderAdapter
from app.services.lager_adapter import LagerAdapter
from app.services.meal_decision import MealDecisionEngine
from app.services.planning import PlanningService
from app.services.profile import ProfileService
from app.services.shopping import ShoppingService
from app.services.stock_forecast import calculate_days_of_food

router = APIRouter(prefix="/api", tags=["spa"])

SLOT_LABELS = {
    "breakfast": "Frühstück",
    "lunch": "Mittagessen",
    "dinner": "Abendessen",
    "snack": "Snack",
    "packed_lunch": "Mitnahme",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_NUTRITION_KEYS = [
    "kcal", "protein_g", "carbs_g", "fat_g", "fiber_g",
    "iron_mg", "zinc_mg", "magnesium_mg", "vitamin_c_mg",
    "vitamin_d_iu", "omega3_g", "calcium_mg",
]


def _nutrition_from_dict(d: dict) -> NutritionInfo:
    """Build NutritionInfo from a dict, defaulting missing keys to 0."""
    return NutritionInfo(**{k: d.get(k, 0) for k in _NUTRITION_KEYS})


def _build_slot(s: MealSlot) -> DashboardSlot:
    """Convert a MealSlot ORM object to a DashboardSlot schema."""
    recipe_info = None
    if s.planned_recipe:
        np = s.planned_recipe.nutrition_per_portion or {}
        recipe_info = SlotRecipeInfo(
            id=s.planned_recipe.id,
            name=s.planned_recipe.name,
            cook_time_min=s.planned_recipe.cook_time_min,
            nutrition=_nutrition_from_dict(np),
            tags=s.planned_recipe.tags,
            instructions=s.planned_recipe.instructions,
        )

    missing = []
    for m in (s.missing_ingredients or []):
        missing.append(MissingIngredient(
            name=m.get("name", ""),
            needed=m.get("needed", 0),
            available=m.get("available", 0),
            unit=m.get("unit", ""),
        ))

    return DashboardSlot(
        id=s.id,
        slot_type=s.slot_type,
        slot_label=SLOT_LABELS.get(s.slot_type, s.slot_type),
        status=s.status,
        recipe=recipe_info,
        pinned=s.pinned,
        feasibility_status=s.feasibility_status,
        missing_ingredients=missing,
    )


def _compute_slot_goal_contribution(
    slot_nutrition: dict,
    remaining_kcal: float,
    remaining_protein: float,
    remaining_carbs: float,
    remaining_fat: float,
) -> GoalContribution:
    """Compute per-slot goal contribution badges."""
    protein = slot_nutrition.get("protein_g", 0)
    carbs = slot_nutrition.get("carbs_g", 0)
    fat = slot_nutrition.get("fat_g", 0)

    protein_label = f"+{protein:.0f}g P" if protein > 0 else ""

    # Carb status relative to remaining
    if remaining_carbs > 0 and carbs > remaining_carbs * 0.6:
        carb_status = "hoch"
    elif remaining_carbs > 0 and carbs < remaining_carbs * 0.1:
        carb_status = "niedrig"
    else:
        carb_status = "ok"

    # Fat status
    if remaining_fat > 0 and fat > remaining_fat * 0.6:
        fat_status = "am Limit"
    else:
        fat_status = "ok"

    return GoalContribution(
        protein_label=protein_label,
        carb_status=carb_status,
        fat_status=fat_status,
    )


def _compute_day_status(
    targets: NutritionInfo,
    intake_totals: NutritionInfo,
    planned_totals: NutritionInfo,
    dashboard_slots: list[DashboardSlot],
) -> DayStatus:
    """Compute overall day status from targets, eaten, and planned totals."""
    target_kcal = targets.kcal or 1
    target_protein = targets.protein_g or 1

    eaten_kcal = intake_totals.kcal
    eaten_protein = intake_totals.protein_g
    planned_kcal = planned_totals.kcal
    planned_protein = planned_totals.protein_g

    total_kcal = eaten_kcal + planned_kcal
    total_protein = eaten_protein + planned_protein

    remaining_kcal = max(0, target_kcal - eaten_kcal)
    remaining_protein = max(0, target_protein - eaten_protein)

    # Count remaining slots (not eaten)
    remaining_slots = sum(1 for s in dashboard_slots if s.status != "eaten")
    remaining_slots_with_recipe = sum(
        1 for s in dashboard_slots if s.status != "eaten" and s.recipe
    )

    # Determine status
    kcal_coverage = total_kcal / target_kcal if target_kcal > 0 else 1
    protein_coverage = total_protein / target_protein if target_protein > 0 else 1

    if kcal_coverage >= 0.85 and protein_coverage >= 0.85:
        status = "on_track"
        status_label = "Auf Kurs"
    elif kcal_coverage >= 0.70 or protein_coverage >= 0.70:
        status = "attention"
        status_label = "Anpassung nötig"
    else:
        status = "at_risk"
        status_label = "Ziel gefährdet"

    # All eaten? Check actual vs target
    if remaining_slots == 0:
        if eaten_kcal >= target_kcal * 0.85 and eaten_protein >= target_protein * 0.85:
            status = "on_track"
            status_label = "Auf Kurs"
        elif eaten_kcal >= target_kcal * 0.70:
            status = "attention"
            status_label = "Anpassung nötig"
        else:
            status = "at_risk"
            status_label = "Ziel gefährdet"

    # Build message
    if remaining_slots == 0:
        message = f"Tag abgeschlossen: {eaten_kcal:.0f} kcal, {eaten_protein:.0f} g Protein"
    else:
        message = (
            f"Noch {remaining_kcal:.0f} kcal und {remaining_protein:.0f} g Protein "
            f"für {remaining_slots} Mahlzeit{'en' if remaining_slots != 1 else ''}"
        )

    # Next meal suggestion: first non-eaten slot with a recipe
    next_meal = None
    for s in dashboard_slots:
        if s.status != "eaten" and s.recipe:
            reason_parts = []
            n = s.recipe.nutrition
            if n and n.protein_g and n.protein_g > 20:
                reason_parts.append(f"Deckt {n.protein_g:.0f}g Protein")
            if n and n.kcal:
                reason_parts.append(f"{n.kcal:.0f} kcal")
            reason = " und ".join(reason_parts) if reason_parts else "Naechste geplante Mahlzeit"

            gc = GoalContribution()
            if s.goal_contribution:
                gc = s.goal_contribution

            next_meal = NextMealSuggestion(
                slot_id=s.id,
                slot_label=s.slot_label,
                recipe_name=s.recipe.name,
                reason=reason,
                goal_contribution=gc,
            )
            break

    return DayStatus(
        status=status,
        status_label=status_label,
        remaining_kcal=round(remaining_kcal, 1),
        remaining_protein_g=round(remaining_protein, 1),
        message=message,
        next_meal=next_meal,
    )


# Micro nutrient reference values and food solutions
_MICRO_REFS = {
    "iron_mg": {"label": "Eisen", "ref": 10, "food": "Rotes Fleisch, Linsen oder Spinat einplanen", "supp": "Eisen-Supplement nehmen"},
    "zinc_mg": {"label": "Zink", "ref": 10, "food": "Fleisch, Kuerbiskerne oder Haferflocken einplanen", "supp": "Zink-Supplement nehmen"},
    "magnesium_mg": {"label": "Magnesium", "ref": 400, "food": "Nuesse, Vollkorn oder Bananen einplanen", "supp": "Magnesium-Supplement nehmen"},
    "vitamin_c_mg": {"label": "Vitamin C", "ref": 100, "food": "Paprika, Zitrusfruechte oder Brokkoli einplanen", "supp": "Vitamin-C-Supplement nehmen"},
    "vitamin_d_iu": {"label": "Vitamin D", "ref": 1000, "food": "Fetter Fisch oder Eier einplanen", "supp": "Vitamin-D-Supplement nehmen"},
    "omega3_g": {"label": "Omega-3", "ref": 2, "food": "Lachs, Makrele oder Walnuesse einplanen", "supp": "Omega-3-Supplement nehmen"},
    "calcium_mg": {"label": "Calcium", "ref": 1000, "food": "Milchprodukte, Brokkoli oder Mandeln einplanen", "supp": "Calcium-Supplement nehmen"},
}


def _compute_nutrient_deficits(
    intake_totals: NutritionInfo,
    planned_totals: NutritionInfo,
) -> list[NutrientDeficit]:
    """Identify micro nutrients with > 50% deficit against reference values."""
    deficits = []
    for key, info in _MICRO_REFS.items():
        eaten = getattr(intake_totals, key, 0) or 0
        planned = getattr(planned_totals, key, 0) or 0
        total = eaten + planned
        ref = info["ref"]
        if ref <= 0:
            continue
        coverage = total / ref
        if coverage < 0.5:
            deficit_pct = round(1 - coverage, 2)
            deficits.append(NutrientDeficit(
                nutrient_label=info["label"],
                deficit_pct=deficit_pct,
                food_solution=info["food"],
                supplement_solution=info["supp"],
            ))
    return deficits


def _build_dashboard_state(target_date: date, db: Session) -> DashboardState:
    """Build the full dashboard state for a given date."""
    lager = LagerAdapter()
    kalender = KalenderAdapter()
    planning_svc = PlanningService(db, lager, kalender)

    # Auto-plan 7 days (skips already-planned days)
    try:
        planning_svc.plan_range(target_date, settings.PLAN_HORIZON_DAYS)
    except Exception as exc:
        log.warning("Auto-plan range fehlgeschlagen: %s", exc)

    # Update feasibility for the current day
    try:
        planning_svc.update_feasibility(target_date)
    except Exception as exc:
        log.warning("Feasibility-Check fehlgeschlagen: %s", exc)

    # Slots for selected day
    slots = list(
        db.execute(
            select(MealSlot)
            .where(MealSlot.date == target_date)
            .order_by(MealSlot.id)
        ).scalars().all()
    )
    # Eagerly load relationships
    for s in slots:
        if s.planned_recipe_id:
            _ = s.planned_recipe

    # Sort by slot order
    slot_order = {"breakfast": 0, "packed_lunch": 1, "lunch": 2, "dinner": 3, "snack": 4}
    slots.sort(key=lambda s: slot_order.get(s.slot_type, 99))

    dashboard_slots = [_build_slot(s) for s in slots]

    # Build 7-day overview
    days: list[DayPlan] = []
    try:
        day_types = kalender.get_day_types_range(target_date, settings.PLAN_HORIZON_DAYS)
    except Exception:
        day_types = {}

    for i in range(settings.PLAN_HORIZON_DAYS):
        d = target_date + timedelta(days=i)
        day_slots = list(
            db.execute(
                select(MealSlot)
                .where(MealSlot.date == d)
                .order_by(MealSlot.id)
            ).scalars().all()
        )
        for s in day_slots:
            if s.planned_recipe_id:
                _ = s.planned_recipe
        day_slots.sort(key=lambda s: slot_order.get(s.slot_type, 99))

        day_dashboard_slots = [_build_slot(s) for s in day_slots]
        days.append(DayPlan(
            date=d,
            day_type=day_types.get(d, "frei"),
            slots=day_dashboard_slots,
        ))

    # Targets - tagesbezogen, wenn fitness eine belastbare Auskunft gibt.
    # Bei duenner Grundlage liefert `tagesziele` das statische Ziel zurueck
    # und sagt im zweiten Wert warum; ausgewertet wird das im Frontend.
    targets = NutritionInfo()
    tagesziel_grund: dict = {}
    try:
        profile_svc = ProfileService(db)
        t, tagesziel_grund = profile_svc.tagesziele(target_date)
        targets = NutritionInfo(
            kcal=t.kcal, protein_g=t.protein_g,
            carbs_g=t.carbs_g, fat_g=t.fat_g, fiber_g=t.fiber_g,
        )
    except Exception as exc:
        log.warning("Failed to derive daily targets: %s", exc)

    # Intake totals (eaten today): includes all keys (macros + micros)
    today_start = datetime.combine(target_date, time.min)
    today_end = datetime.combine(target_date, time.max)
    intake_items = list(
        db.execute(
            select(IntakeItem).where(
                IntakeItem.timestamp >= today_start,
                IntakeItem.timestamp <= today_end,
            )
        ).scalars().all()
    )
    intake = {k: 0 for k in _NUTRITION_KEYS}
    for item in intake_items:
        n = item.nutrients or {}
        for key in intake:
            intake[key] += n.get(key, 0)
    intake_totals = NutritionInfo(**intake)

    # Planned totals (non-eaten slots with recipes)
    planned = {k: 0 for k in _NUTRITION_KEYS}
    for s in slots:
        if s.planned_recipe and s.status != "eaten":
            n = s.planned_recipe.nutrition_per_portion or {}
            for key in planned:
                planned[key] += n.get(key, 0)
    planned_totals = NutritionInfo(**planned)

    # Adhoc intakes (no meal_slot_id, for current day)
    adhoc_items = [
        item for item in intake_items if item.meal_slot_id is None
    ]
    adhoc_intakes = [
        IntakeLogOut(
            id=item.id,
            label=item.label,
            nutrition=_nutrition_from_dict(item.nutrients) if item.nutrients else None,
            timestamp=item.timestamp,
            source_type=item.source_type,
        )
        for item in adhoc_items
    ]

    # Days of food. ★ Der Fehlerfall setzt `belastbar` NICHT auf True: eine
    # 0 aus einer Ausnahme sah im Dashboard genauso aus wie ein leerer Vorrat.
    days_of_food = 0.0
    days_of_food_belastbar = False
    days_of_food_grund = "Die Vorratsreichweite wurde nicht berechnet."
    try:
        forecast = calculate_days_of_food(db, lager)
        days_of_food = forecast.days
        days_of_food_belastbar = forecast.belastbar
        days_of_food_grund = forecast.grund
    except Exception as exc:
        log.warning("Failed to calculate days of food: %s", exc)
        days_of_food_grund = "Die Vorratsreichweite liess sich nicht berechnen."

    # Planned dates
    try:
        planned_dates = planning_svc.get_planned_dates()
    except Exception as exc:
        log.warning("Failed to get planned dates: %s", exc)
        planned_dates = []

    # Supplements + conditional hints
    supplement_hints = _build_supplement_hints(db, target_date, slots)
    supplements = _get_supplements(db, target_date, supplement_hints)

    # Aggregate supplement nutrition into totals
    for supp_out in supplements:
        if supp_out.nutrition is None:
            continue
        n_dict = supp_out.nutrition.model_dump()
        target = intake_totals if supp_out.taken_today else planned_totals
        for key in _NUTRITION_KEYS:
            setattr(target, key, getattr(target, key) + n_dict.get(key, 0))

    # Compute per-slot goal contributions and slot status
    remaining_kcal_running = max(0, targets.kcal - intake_totals.kcal)
    remaining_protein_running = max(0, targets.protein_g - intake_totals.protein_g)
    remaining_carbs_running = max(0, targets.carbs_g - intake_totals.carbs_g)
    remaining_fat_running = max(0, targets.fat_g - intake_totals.fat_g)

    for ds in dashboard_slots:
        if ds.status == "eaten" or not ds.recipe or not ds.recipe.nutrition:
            continue
        n = ds.recipe.nutrition
        n_dict = n.model_dump() if n else {}
        ds.goal_contribution = _compute_slot_goal_contribution(
            n_dict,
            remaining_kcal_running,
            remaining_protein_running,
            remaining_carbs_running,
            remaining_fat_running,
        )
        # Determine slot_status
        slot_kcal = n_dict.get("kcal", 0)
        slot_protein = n_dict.get("protein_g", 0)
        is_feasible = ds.feasibility_status != "infeasible"
        # Simple heuristic: "optimal" if feasible and covers decent protein/kcal
        uneaten_count = sum(1 for s in dashboard_slots if s.status != "eaten")
        ideal_kcal = remaining_kcal_running / max(uneaten_count, 1)
        ideal_protein = remaining_protein_running / max(uneaten_count, 1)
        if is_feasible and ideal_kcal > 0:
            kcal_fit = max(0, 1.0 - abs(slot_kcal - ideal_kcal) / ideal_kcal) if ideal_kcal > 0 else 0.5
            protein_fit = max(0, 1.0 - abs(slot_protein - ideal_protein) / ideal_protein) if ideal_protein > 0 else 0.5
            combined = 0.5 * protein_fit + 0.5 * kcal_fit
            if combined > 0.5:
                ds.slot_status = "optimal"
            else:
                ds.slot_status = "planned"
        elif not is_feasible:
            ds.slot_status = "replace_recommended"
        else:
            ds.slot_status = "planned"

        # Deduct from running totals for next slot calculation
        remaining_kcal_running = max(0, remaining_kcal_running - slot_kcal)
        remaining_protein_running = max(0, remaining_protein_running - slot_protein)
        remaining_carbs_running = max(0, remaining_carbs_running - n_dict.get("carbs_g", 0))
        remaining_fat_running = max(0, remaining_fat_running - n_dict.get("fat_g", 0))

    # Compute day status
    day_status = None
    if targets.kcal > 0:
        day_status = _compute_day_status(
            targets, intake_totals, planned_totals, dashboard_slots,
        )

    # Compute nutrient deficits
    nutrient_deficits = _compute_nutrient_deficits(intake_totals, planned_totals)

    return DashboardState(
        date=target_date,
        slots=dashboard_slots,
        targets=targets,
        intake_totals=intake_totals,
        planned_totals=planned_totals,
        days_of_food=days_of_food,
        days_of_food_belastbar=days_of_food_belastbar,
        days_of_food_grund=days_of_food_grund,
        planned_dates=planned_dates,
        days=days,
        supplements=supplements,
        adhoc_intakes=adhoc_intakes,
        supplement_hints=[h for h in supplement_hints.values()],
        day_status=day_status,
        nutrient_deficits=nutrient_deficits,
        tagesziel=tagesziel_grund or None,
    )


def _get_shopping_info(db: Session) -> ShoppingInfo:
    """Get current open shopping list as ShoppingInfo."""
    sl = db.execute(
        select(ShoppingList)
        .where(ShoppingList.status == "open")
        .order_by(ShoppingList.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not sl:
        return ShoppingInfo()

    lines = []
    for line in sl.lines:
        ing = db.get(Ingredient, line.ingredient_id)
        lines.append(ShoppingLine(
            ingredient=ing.name_canonical if ing else f"#{line.ingredient_id}",
            amount=line.needed_amount,
            unit=line.unit,
            reasons=line.reason_codes,
        ))
    return ShoppingInfo(lines=lines)


def _build_supplement_hints(
    db: Session, target_date: date, slots: list[MealSlot],
) -> dict[int, str]:
    """Check conditional supplements against the day plan.

    Returns a dict mapping supplement_id -> hint string for supplements
    whose condition_tag is NOT found among the day's recipe tags.
    """
    conditionals = list(
        db.execute(
            select(Supplement).where(
                Supplement.active.is_(True),
                Supplement.category == "conditional",
                Supplement.condition_tag.isnot(None),
            )
        ).scalars().all()
    )
    if not conditionals:
        return {}

    # Collect all tags from planned recipes for the day
    day_tags: set[str] = set()
    for s in slots:
        if s.planned_recipe:
            day_tags.update(t.lower() for t in s.planned_recipe.tags)

    hints: dict[int, str] = {}
    for supp in conditionals:
        tag = supp.condition_tag.lower() if supp.condition_tag else ""
        if tag and tag not in day_tags:
            hints[supp.id] = f"{supp.name}: kein {supp.condition_tag} im Plan"
    return hints


def _get_supplements(
    db: Session,
    target_date: date,
    hints: dict[int, str] | None = None,
) -> list[SupplementOut]:
    """Load active supplements with taken_today status and conditional hints."""
    supps = list(
        db.execute(
            select(Supplement)
            .where(Supplement.active.is_(True))
            .order_by(Supplement.sort_order, Supplement.id)
        ).scalars().all()
    )
    if not supps:
        return []

    hints = hints or {}

    # Load logs for target date
    supp_ids = [s.id for s in supps]
    logs = list(
        db.execute(
            select(SupplementLog).where(
                SupplementLog.supplement_id.in_(supp_ids),
                SupplementLog.date == target_date,
            )
        ).scalars().all()
    )
    taken_ids = {lg.supplement_id for lg in logs if lg.taken}

    return [
        SupplementOut(
            id=s.id,
            name=s.name,
            dose=s.dose,
            timing=s.timing,
            taken_today=s.id in taken_ids,
            category=s.category or "daily",
            condition_tag=s.condition_tag,
            hint=hints.get(s.id),
            nutrition=_nutrition_from_dict(s.nutrition) if s.nutrition else None,
        )
        for s in supps
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/dashboard/{target_date}", response_model=DashboardState)
def get_dashboard(target_date: date, db: Session = Depends(get_db)):
    return _build_dashboard_state(target_date, db)


def _fetch_fitness_context(target_date: date) -> dict:
    """Trainingskontext des Tages aus fitness.

    ★ Stand bis zum 2026-09-13 als eigener httpx-Aufruf hier und schickte
    dabei **keinen** ``X-Saganta-Sub``: der Tagescoach las die Trainings des
    Vorgabe-Mandanten statt die des angemeldeten Nutzers. Der Aufruf lebt
    jetzt im ``FitnessAdapter``, wo die Mandanten-Kopfzeilen entstehen, damit
    dieselbe Luecke nicht an der naechsten Stelle wieder aufgeht.
    """
    return FitnessAdapter().tageskontext(target_date)


def _nutrition_dump(n) -> dict:
    return n.model_dump() if hasattr(n, "model_dump") else dict(n or {})


@router.get("/day-coach/{target_date}")
def get_day_coach(target_date: date, db: Session = Depends(get_db)):
    """Cross-service day coach: MealPrep + Lager + Kalender + Fitness."""
    dashboard = _build_dashboard_state(target_date, db)
    kalender = KalenderAdapter()
    lager = LagerAdapter()
    fitness = _fetch_fitness_context(target_date)

    day_type = kalender.get_day_type(target_date)
    needs_packed_lunch = kalender.needs_packed_lunch(target_date)
    targets = _nutrition_dump(dashboard.targets)
    eaten = _nutrition_dump(dashboard.intake_totals)
    planned = _nutrition_dump(dashboard.planned_totals)

    remaining = {
        "kcal": max(0, targets.get("kcal", 0) - eaten.get("kcal", 0)),
        "protein_g": max(0, targets.get("protein_g", 0) - eaten.get("protein_g", 0)),
        "carbs_g": max(0, targets.get("carbs_g", 0) - eaten.get("carbs_g", 0)),
        "fat_g": max(0, targets.get("fat_g", 0) - eaten.get("fat_g", 0)),
    }

    planned_total_kcal = eaten.get("kcal", 0) + planned.get("kcal", 0)
    target_kcal = targets.get("kcal", 0) or 1
    planned_coverage = round(planned_total_kcal / target_kcal, 2)

    planned_day = fitness.get("planned_day")
    workouts = fitness.get("workouts", [])
    has_training = bool(planned_day) or bool(workouts)
    completed_training = any(w.get("finished_at") for w in workouts)

    expiring = lager.get_expiring(days=3)[:6]

    actions: list[str] = []
    if needs_packed_lunch and not any(s.slot_type == "packed_lunch" and s.recipe for s in dashboard.slots):
        actions.append("Mitnahme fuer den Arbeitstag einplanen.")
    if has_training and not completed_training:
        actions.append("Vor dem Training eine leichte Mahlzeit mit Protein und gut vertraeglichen Kohlenhydraten lassen.")
    if remaining["protein_g"] > 40:
        actions.append(f"Noch etwa {remaining['protein_g']:.0f} g Protein offen.")
    if planned_coverage < 0.85:
        actions.append("Tagesplan deckt das Kalorienziel noch nicht sauber ab.")
    if expiring:
        names = ", ".join(str(x.get("product_name") or x.get("name") or "Vorrat") for x in expiring[:3])
        actions.append(f"Ablaufende Vorraete zuerst verbrauchen: {names}.")
    if dashboard.tagesziel and dashboard.tagesziel.verschoben:
        actions.append(
            "Trainingstag: mehr Kohlenhydrate als sonst."
            if dashboard.tagesziel.trainingstag else
            "Ruhetag: weniger Kohlenhydrate als an Trainingstagen."
        )
    if not actions:
        actions.append("Plan steht. Naechste Mahlzeit wie geplant essen.")

    timing: list[dict] = []
    if has_training:
        timing.append({
            "label": "Training",
            "text": "2-3 Stunden vorher eine normale Mahlzeit, 30-60 Minuten vorher nur leicht.",
        })
        timing.append({
            "label": "Nach dem Training",
            "text": "Protein priorisieren und die naechste geplante Mahlzeit nicht ausfallen lassen.",
        })
    if needs_packed_lunch:
        timing.append({
            "label": "Unterwegs",
            "text": "Mitnahme einpacken, damit der Plan nicht vom Arbeitstag abhaengt.",
        })

    return {
        "date": target_date,
        "day_type": day_type,
        "needs_packed_lunch": needs_packed_lunch,
        "targets": targets,
        "eaten": eaten,
        "planned": planned,
        "remaining": remaining,
        "planned_coverage": planned_coverage,
        "day_status": dashboard.day_status.model_dump() if dashboard.day_status else None,
        "tagesziel": dashboard.tagesziel.model_dump() if dashboard.tagesziel else None,
        "fitness": fitness,
        "has_training": has_training,
        "completed_training": completed_training,
        "expiring": expiring,
        "actions": actions,
        "timing": timing,
    }


@router.get("/swap-candidates/{slot_id}", response_model=SwapCandidatesResponse)
def get_swap_candidates(slot_id: int, db: Session = Depends(get_db)):
    slot = db.get(MealSlot, slot_id)
    if not slot:
        raise DomainError("Meal-Slot nicht gefunden", {"slot_id": slot_id})

    lager = LagerAdapter()
    profile_svc = ProfileService(db)
    profile = profile_svc.get_or_create()
    excluded_ids = set(profile.excluded_ingredient_ids)
    user_allergens = {a.lower() for a in (profile.allergies + profile.intolerances)}
    engine = MealDecisionEngine(
        db, lager,
        excluded_ingredient_ids=excluded_ids,
        user_allergens=user_allergens,
    )

    phase = db.execute(
        select(GoalPhase).where(GoalPhase.is_active.is_(True))
    ).scalar_one_or_none()

    # Build day context from existing slots
    day_context = None
    try:
        profile_svc = ProfileService(db)
        targets = profile_svc.derive_daily_targets()
        day_slots = list(
            db.execute(
                select(MealSlot).where(MealSlot.date == slot.date)
            ).scalars().all()
        )
        day_context = DayNutritionContext(
            targets=targets,
            slot_count_total=len(day_slots) or 1,
        )
        # Accumulate nutrition from eaten + other planned slots
        for s in day_slots:
            if s.id == slot_id:
                continue
            if s.planned_recipe:
                np = s.planned_recipe.nutrition_per_portion or {}
                day_context.add_planned(np)
    except Exception as exc:
        log.warning("Failed to build day nutrition context: %s", exc)

    candidates = engine.score_all_for_slot(
        slot, phase, day_context=day_context, include_infeasible=True,
    )

    recipes = []
    for c in candidates:
        r = c["recipe"]
        np = r.nutrition_per_portion or {}
        recipes.append(SwapCandidateRecipe(
            id=r.id,
            name=r.name,
            cook_time_min=r.cook_time_min,
            nutrition=NutritionInfo(**{k: np.get(k, 0) for k in ["kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]}),
            tags=r.tags,
            score=c["score"],
            feasible=c["feasible"],
            missing_ingredients=[
                MissingIngredient(**m) for m in c["missing_ingredients"]
            ],
        ))

    return SwapCandidatesResponse(
        recipes=recipes,
        slot_id=slot_id,
        show_infeasible=True,
    )


@router.get("/days-of-food", response_model=DaysOfFoodResult)
def get_days_of_food(db: Session = Depends(get_db)):
    lager = LagerAdapter()
    return calculate_days_of_food(db, lager)


class SwapRequest(BaseModel):
    recipe_id: int


@router.post("/slots/{slot_id}/swap", response_model=DashboardState)
def swap_slot(slot_id: int, body: SwapRequest, db: Session = Depends(get_db)):
    slot = db.get(MealSlot, slot_id)
    if not slot:
        raise DomainError("Meal-Slot nicht gefunden", {"slot_id": slot_id})

    recipe = db.get(Recipe, body.recipe_id)
    if not recipe:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": body.recipe_id})

    slot.planned_recipe_id = body.recipe_id
    slot.status = "planned"
    slot.pinned = True
    db.commit()

    # Auto-refresh shopping
    lager = LagerAdapter()
    try:
        shopping_svc = ShoppingService(db, lager)
        shopping_svc.auto_refresh(slot.date)
    except Exception as exc:
        log.warning("Failed to refresh shopping after swap: %s", exc)

    return _build_dashboard_state(slot.date, db)


@router.post("/slots/{slot_id}/commit", response_model=DashboardState)
def commit_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.get(MealSlot, slot_id)
    if not slot:
        raise DomainError("Meal-Slot nicht gefunden", {"slot_id": slot_id})
    if not slot.planned_recipe_id:
        raise DomainError("Kein Rezept geplant fuer diesen Slot")

    recipe = db.get(Recipe, slot.planned_recipe_id)
    if not recipe:
        raise DomainError("Rezept nicht gefunden")

    # Consume from Lager (best effort)
    lager = LagerAdapter()
    ri_rows = list(
        db.execute(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id
            )
        ).scalars().all()
    )

    try:
        consume_items = []
        for ri in ri_rows:
            if ri.optional_bool:
                continue
            ing = db.get(Ingredient, ri.ingredient_id)
            if not ing or not ing.lager_product_id:
                continue
            consume_items.append({
                "product_id": ing.lager_product_id,
                "amount": ri.amount,
                "unit": ri.unit,
            })
        if consume_items:
            lager.consume_recipe(
                ingredients=consume_items,
                source="mealprep",
                ref_type="recipe",
                ref_id=recipe.id,
            )
    except Exception as exc:
        log.warning("Failed to consume from Lager: %s", exc)

    # Track intake
    n = recipe.nutrition_per_portion or {}
    intake = IntakeItem(
        source_type="RECIPE_PORTION",
        source_id=slot.planned_recipe_id,
        amount=1,
        unit="portion",
        meal_slot_id=slot.id,
    )
    intake.nutrients = dict(n)
    db.add(intake)

    slot.status = "eaten"
    db.commit()

    # Refresh feasibility for all planned dates (stock has changed)
    try:
        kalender = KalenderAdapter()
        planning_svc = PlanningService(db, lager, kalender)
        refreshed = planning_svc.refresh_all_feasibility()
        if refreshed:
            log.info("Feasibility aktualisiert fuer %d Tage nach Commit", refreshed)
    except Exception as exc:
        log.warning("Feasibility-Refresh nach Commit fehlgeschlagen: %s", exc)

    # Auto-refresh shopping
    try:
        shopping_svc = ShoppingService(db, lager)
        shopping_svc.auto_refresh(slot.date)
    except Exception as exc:
        log.warning("Failed to refresh shopping after commit: %s", exc)

    return _build_dashboard_state(slot.date, db)


@router.post("/plan/{target_date}", response_model=DashboardState)
def plan_day(target_date: date, db: Session = Depends(get_db)):
    lager = LagerAdapter()
    kalender = KalenderAdapter()
    svc = PlanningService(db, lager, kalender)
    svc.plan_day(target_date)
    return _build_dashboard_state(target_date, db)


@router.post("/replan/{target_date}", response_model=DashboardState)
def replan_day(target_date: date, db: Session = Depends(get_db)):
    lager = LagerAdapter()
    kalender = KalenderAdapter()
    svc = PlanningService(db, lager, kalender)
    svc.replan_day(target_date)
    return _build_dashboard_state(target_date, db)


# ---------------------------------------------------------------------------
# Supplement endpoints
# ---------------------------------------------------------------------------


@router.get("/supplements", response_model=list[SupplementOut])
def get_supplements(
    target_date: date | None = None,
    db: Session = Depends(get_db),
):
    d = target_date or date.today()
    return _get_supplements(db, d)


@router.post("/supplements/{supplement_id}/toggle", response_model=SupplementOut)
def toggle_supplement(
    supplement_id: int,
    target_date: date | None = None,
    db: Session = Depends(get_db),
):
    d = target_date or date.today()
    supp = db.get(Supplement, supplement_id)
    if not supp:
        raise DomainError("Supplement nicht gefunden", {"id": supplement_id})

    existing = db.execute(
        select(SupplementLog).where(
            SupplementLog.supplement_id == supplement_id,
            SupplementLog.date == d,
        )
    ).scalar_one_or_none()

    if existing:
        # Toggle: delete the log entry (un-take)
        db.delete(existing)
        taken = False
    else:
        # Mark as taken
        log_entry = SupplementLog(supplement_id=supplement_id, date=d, taken=True)
        db.add(log_entry)
        taken = True

    db.commit()

    return SupplementOut(
        id=supp.id,
        name=supp.name,
        dose=supp.dose,
        timing=supp.timing,
        taken_today=taken,
        category=supp.category or "daily",
        condition_tag=supp.condition_tag,
        nutrition=_nutrition_from_dict(supp.nutrition) if supp.nutrition else None,
    )


# ---------------------------------------------------------------------------
# Ad-hoc Intake endpoints
# ---------------------------------------------------------------------------


@router.post("/intake/log", response_model=DashboardState)
def log_adhoc_intake(
    body: IntakeLogRequest,
    target_date: date | None = None,
    db: Session = Depends(get_db),
):
    """Log an ad-hoc meal (outside planned slots)."""
    d = target_date or date.today()

    label = body.label
    nutrients: dict = {}

    if body.recipe_id:
        recipe = db.get(Recipe, body.recipe_id)
        if not recipe:
            raise DomainError("Rezept nicht gefunden", {"recipe_id": body.recipe_id})
        label = label or recipe.name
        nutrients = dict(recipe.nutrition_per_portion or {})
    elif body.nutrition:
        nutrients = body.nutrition.model_dump()
    # else: label-only intake with no nutrition

    if not label:
        raise DomainError("Label oder recipe_id erforderlich")

    intake = IntakeItem(
        source_type="ADHOC" if not body.recipe_id else "RECIPE_PORTION",
        source_id=body.recipe_id,
        amount=body.amount,
        unit=body.unit,
        meal_slot_id=None,
        label=label,
        timestamp=datetime.combine(d, datetime.now().time()),
    )
    intake.nutrients = nutrients
    db.add(intake)
    db.commit()

    return _build_dashboard_state(d, db)


@router.delete("/intake/{intake_id}", response_model=DashboardState)
def delete_adhoc_intake(
    intake_id: int,
    db: Session = Depends(get_db),
):
    """Delete an ad-hoc intake item (only non-slot-bound)."""
    item = db.get(IntakeItem, intake_id)
    if not item:
        raise DomainError("Intake nicht gefunden", {"id": intake_id})
    if item.meal_slot_id is not None:
        raise DomainError("Slot-gebundene Intakes koennen nicht direkt geloescht werden")

    # Determine date from timestamp for dashboard rebuild
    d = item.timestamp.date() if item.timestamp else date.today()

    db.delete(item)
    db.commit()

    return _build_dashboard_state(d, db)


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    period: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Aggregate intake stats for the last N days."""
    today = date.today()
    start = today - timedelta(days=period - 1)

    # Get all intake items in the period
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(today, time.max)
    items = list(
        db.execute(
            select(IntakeItem).where(
                IntakeItem.timestamp >= start_dt,
                IntakeItem.timestamp <= end_dt,
            )
        ).scalars().all()
    )

    # Aggregate per day
    day_map: dict[date, dict] = {}
    for d_offset in range(period):
        d = start + timedelta(days=d_offset)
        day_map[d] = {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}

    for item in items:
        d = item.timestamp.date() if item.timestamp else today
        if d not in day_map:
            continue
        n = item.nutrients or {}
        for key in day_map[d]:
            day_map[d][key] += n.get(key, 0)

    days_list = [
        DayStats(date=d, **vals)
        for d, vals in sorted(day_map.items())
    ]

    total_kcal = sum(d.kcal for d in days_list)
    total_protein = sum(d.protein_g for d in days_list)
    n_days = len(days_list) or 1

    return StatsResponse(
        days=days_list,
        avg_kcal=round(total_kcal / n_days, 1),
        avg_protein_g=round(total_protein / n_days, 1),
        period_days=period,
    )
