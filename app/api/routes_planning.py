"""Planning routes: slot CRUD, plan a day/week, commit a meal slot via Lager."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import DomainError
from app.models import Ingredient, IntakeItem, MealSlot, Recipe, RecipeIngredient
from app.schemas import MealSlotCreate, MealSlotOut, MealSlotUpdate, PlanDayResult
from app.services import lager_dringend
from app.services.lager_adapter import LagerAdapter
from app.services.planning import PlanningService
from app.services.shopping import ShoppingService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["planning"])
templates = Jinja2Templates(directory="app/templates")


# ----- Slot CRUD -----

@router.get("/slots", response_model=list[MealSlotOut])
def list_slots(target_date: date | None = None, db: Session = Depends(get_db)):
    q = select(MealSlot)
    if target_date:
        q = q.where(MealSlot.date == target_date)
    rows = db.execute(q).scalars().all()
    return [_slot_out(s) for s in rows]


@router.post("/slots", response_model=MealSlotOut, status_code=201)
def create_slot(body: MealSlotCreate, db: Session = Depends(get_db)):
    slot = MealSlot(
        date=body.date,
        slot_type=body.slot_type,
        time_window_start=body.time_window_start,
        time_window_end=body.time_window_end,
        planned_recipe_id=body.planned_recipe_id,
        status="planned",
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return _slot_out(slot)


@router.put("/slots/{slot_id}", response_model=MealSlotOut)
def update_slot(slot_id: int, body: MealSlotUpdate, db: Session = Depends(get_db)):
    slot = db.get(MealSlot, slot_id)
    if not slot:
        raise DomainError("Meal-Slot nicht gefunden", {"slot_id": slot_id})
    data = body.model_dump(exclude_unset=True)
    for key, val in data.items():
        setattr(slot, key, val)
    db.commit()
    db.refresh(slot)
    return _slot_out(slot)


@router.delete("/slots/{slot_id}", status_code=204)
def delete_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.get(MealSlot, slot_id)
    if not slot:
        raise DomainError("Meal-Slot nicht gefunden", {"slot_id": slot_id})
    db.delete(slot)
    db.commit()


# ----- Week planning (must be before /{target_date} catch-all) -----


WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAY_FULL = [
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
]


@router.post("/week")
def plan_week(
    start_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    """Plan an entire week starting from start_date (defaults to current Monday)."""
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())

    svc = PlanningService(db)
    summary = svc.plan_week(start_date)
    return {"start_date": start_date, "days": summary}


@router.get("/week/shopping")
def week_shopping_list(
    start_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    """Get aggregated shopping list for a week."""
    if start_date is None:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())

    lager = LagerAdapter()
    svc = ShoppingService(db, lager)
    items = svc.get_weekly_shopping_list(start_date, days=7)
    # Was weg muss, gehoert neben das, was gekauft werden soll: sonst kauft man
    # nach, was im Vorrat gerade verdirbt. Die API-Seite bekommt dasselbe wie
    # die Ansicht, damit sie nicht dahinter zurueckbleibt.
    return {
        "start_date": start_date,
        "items": items,
        "muss_weg": lager_dringend.was_muss_weg(lager),
    }


@router.get("/wochenplan", response_class=HTMLResponse)
def week_plan_view(
    request: Request,
    start_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    """Render the weekly meal plan template."""
    today = date.today()
    if start_date is None:
        start_date = today - timedelta(days=today.weekday())

    # Ensure start_date is a Monday
    start_date = start_date - timedelta(days=start_date.weekday())

    svc = PlanningService(db)
    summary = svc.plan_week(start_date)

    # Compute total kcal and protein per day for display
    for day_data in summary:
        total_kcal = 0.0
        total_protein = 0.0
        for meal in day_data["meals"]:
            if meal["nutrition"]:
                n = meal["nutrition"]
                total_kcal += n.get("kcal", 0) if isinstance(n, dict) else 0
                total_protein += n.get("protein_g", 0) if isinstance(n, dict) else 0
        day_data["total_kcal"] = round(total_kcal)
        day_data["total_protein"] = round(total_protein, 1)

    # Get shopping list
    lager = LagerAdapter()
    shopping_svc = ShoppingService(db, lager)
    try:
        shopping_items = shopping_svc.get_weekly_shopping_list(start_date, days=7)
    except Exception as exc:
        log.warning("Einkaufsliste konnte nicht geladen werden: %s", exc)
        shopping_items = []

    try:
        muss_weg = lager_dringend.was_muss_weg(lager)
    except Exception as exc:
        log.warning("Dringende Lager-Posten nicht abrufbar: %s", exc)
        muss_weg = {"erreichbar": False, "posten": [], "grund": str(exc)}

    # Navigation dates
    prev_week = start_date - timedelta(weeks=1)
    next_week = start_date + timedelta(weeks=1)

    # Week label
    end_date = start_date + timedelta(days=6)
    week_label = f"{start_date.strftime('%d.%m.')} - {end_date.strftime('%d.%m.%Y')}"

    return templates.TemplateResponse(request, "plan_week.html", {
        "request": request,
        "start_date": start_date,
        "today": today,
        "days": summary,
        "weekday_labels": WEEKDAY_LABELS,
        "weekday_full": WEEKDAY_FULL,
        "shopping_items": shopping_items,
        "muss_weg": muss_weg,
        "prev_week": prev_week,
        "next_week": next_week,
        "week_label": week_label,
        "active_nav": "wochenplan",
    })


# ----- Auto-plan -----

@router.post("/today", response_model=PlanDayResult)
def plan_today(db: Session = Depends(get_db)):
    svc = PlanningService(db)
    return svc.plan_day(date.today())


@router.post("/{target_date}", response_model=PlanDayResult)
def plan_date(target_date: date, db: Session = Depends(get_db)):
    svc = PlanningService(db)
    return svc.plan_day(target_date)


# ----- Commit (Gegessen) -----

@router.post("/meal-slots/{slot_id}/commit")
def commit_slot(slot_id: int, portions: int = Query(1, ge=1, le=20), db: Session = Depends(get_db)):
    slot = db.get(MealSlot, slot_id)
    if not slot:
        raise DomainError("Meal-Slot nicht gefunden", {"slot_id": slot_id})
    if not slot.planned_recipe_id:
        raise DomainError("Kein Rezept geplant fuer diesen Slot")

    recipe = db.get(Recipe, slot.planned_recipe_id)
    if not recipe:
        raise DomainError("Rezept nicht gefunden")

    # Build consume-recipe payload for Lager
    ri_rows = list(
        db.execute(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id
            )
        ).scalars().all()
    )

    lager = LagerAdapter()
    consume_items = []
    unmapped = []
    for ri in ri_rows:
        if ri.optional_bool:
            continue
        ing = db.get(Ingredient, ri.ingredient_id)
        if not ing or not ing.lager_product_id:
            unmapped.append(ing.name_canonical if ing else f"#{ri.ingredient_id}")
            continue
        consume_items.append({
            "product_id": ing.lager_product_id,
            "amount": ri.amount * portions,
            "unit": ri.unit,
        })

    if unmapped:
        raise DomainError(
            "Zutaten ohne Lager-Verknuepfung",
            {"unmapped_ingredients": unmapped},
        )

    # Atomic consume via Lager
    events = lager.consume_recipe(
        ingredients=consume_items,
        source="mealprep",
        ref_type="recipe",
        ref_id=recipe.id,
    )

    # Create intake record
    n = recipe.nutrition_per_portion or {}
    scaled = {}
    if n:
        for k, v in n.items():
            scaled[k] = round(v * portions, 2)

    intake = IntakeItem(
        source_type="RECIPE_PORTION",
        source_id=slot.planned_recipe_id,
        amount=portions,
        unit="portion",
        meal_slot_id=slot.id,
    )
    intake.nutrients = scaled
    db.add(intake)

    slot.status = "eaten"
    db.commit()

    # Refresh feasibility for all planned dates (stock has changed)
    try:
        svc = PlanningService(db)
        refreshed = svc.refresh_all_feasibility()
        if refreshed:
            log.info("Feasibility aktualisiert fuer %d Tage nach Commit", refreshed)
    except Exception as exc:
        log.warning("Feasibility-Refresh nach Commit fehlgeschlagen: %s", exc)

    return {
        "status": "ok",
        "lager_events": len(events),
        "intake_nutrients": scaled,
    }


def _slot_out(s: MealSlot) -> MealSlotOut:
    recipe_name = None
    if s.planned_recipe and s.planned_recipe_id:
        recipe_name = s.planned_recipe.name
    return MealSlotOut(
        id=s.id,
        date=s.date,
        slot_type=s.slot_type,
        status=s.status,
        planned_recipe_id=s.planned_recipe_id,
        planned_recipe_name=recipe_name,
    )
