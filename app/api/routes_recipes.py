"""Recipe CRUD routes (JSON API + HTML UI)."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import DomainError
from app.models import GoalPhase, Ingredient, MealSlot, Recipe, RecipeIngredient
from app.schemas import (
    DayNutritionContext,
    GoalMatchInfo,
    RecipeCreate,
    RecipeIngredientOut,
    RecipeOut,
    RecipeUpdate,
)
from app.services.lager_adapter import LagerAdapter
from app.services.meal_decision import MealDecisionEngine
from app.services.profile import ProfileService
from app.services.recipes import RecipesService

router = APIRouter(prefix="/recipes", tags=["recipes"])
html_router = APIRouter(prefix="/rezepte", tags=["rezepte-ui"])
ingredients_html_router = APIRouter(prefix="/zutaten", tags=["zutaten-ui"])
templates = Jinja2Templates(directory="app/templates")

# EU-14 Hauptallergene (shared with routes_dashboard)
EU14_ALLERGENS = [
    {"key": "gluten", "label": "Gluten"},
    {"key": "krebstiere", "label": "Krebstiere"},
    {"key": "eier", "label": "Eier"},
    {"key": "fisch", "label": "Fisch"},
    {"key": "erdnuesse", "label": "Erdnuesse"},
    {"key": "soja", "label": "Soja"},
    {"key": "laktose", "label": "Milch/Laktose"},
    {"key": "schalen", "label": "Schalenfruechte"},
    {"key": "sellerie", "label": "Sellerie"},
    {"key": "senf", "label": "Senf"},
    {"key": "sesam", "label": "Sesam"},
    {"key": "sulfite", "label": "Sulfite"},
    {"key": "lupine", "label": "Lupine"},
    {"key": "weichtiere", "label": "Weichtiere"},
]


def _recipe_to_out(r: Recipe) -> RecipeOut:
    ingredients = []
    for ri in r.ingredients:
        ing = ri.ingredient
        ingredients.append(RecipeIngredientOut(
            id=ri.id,
            ingredient_id=ri.ingredient_id,
            ingredient_name=ing.name_canonical if ing else "",
            amount=ri.amount,
            unit=ri.unit,
            optional_bool=ri.optional_bool,
        ))
    return RecipeOut(
        id=r.id,
        name=r.name,
        portions_default=r.portions_default,
        cook_time_min=r.cook_time_min,
        tags=r.tags,
        nutrition_per_portion=r.nutrition_per_portion,
        ingredients=ingredients,
        instructions=r.instructions,
    )


def _ingredient_categories(r: Recipe) -> list[str]:
    """Extract unique ingredient categories for canvas rendering."""
    cats = []
    for ri in r.ingredients:
        if ri.ingredient and ri.ingredient.category:
            cats.append(ri.ingredient.category)
    return cats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_excluded_ids(db: Session) -> list[int]:
    """Load excluded ingredient IDs from user profile."""
    svc = ProfileService(db)
    p = svc.get_or_create()
    return p.excluded_ingredient_ids


def _get_user_allergens(db: Session) -> set[str]:
    """Load combined allergens + intolerances from user profile (lowercase)."""
    svc = ProfileService(db)
    p = svc.get_or_create()
    return {a.lower() for a in (p.allergies + p.intolerances)}


# ---------------------------------------------------------------------------
# JSON API routes (/recipes)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[RecipeOut])
def list_recipes(
    q: str = Query("", description="Suchbegriff"),
    tags: str = Query("", description="kommagetrennte Tags"),
    max_time: int | None = Query(None, description="max Kochzeit"),
    max_kcal: float | None = Query(None, description="max kcal"),
    include_hidden: bool = Query(False, description="ausgeblendete Rezepte mitliefern"),
    db: Session = Depends(get_db),
):
    svc = RecipesService(db)
    excluded = _get_excluded_ids(db)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    has_filter = q or tag_list or max_time or max_kcal
    if has_filter:
        recipes = svc.filter(
            q=q, tags=tag_list, max_cook_time=max_time, max_kcal=max_kcal,
            excluded_ingredient_ids=excluded, include_hidden=include_hidden,
        )
    else:
        recipes = svc.list_all(
            excluded_ingredient_ids=excluded, include_hidden=include_hidden,
        )
    out = []
    hidden_ids = svc.hidden_recipe_ids() if include_hidden else set()
    for r in recipes:
        item = _recipe_to_out(r)
        if include_hidden and r.id in hidden_ids:
            item.hidden = True
        out.append(item)
    return out


@router.post("/{recipe_id}/hide", status_code=204)
def hide_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Rezept fuer den aktuellen Nutzer ausblenden (globale bleiben fuer andere sichtbar)."""
    if not RecipesService(db).hide(recipe_id):
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    db.commit()


@router.delete("/{recipe_id}/hide", status_code=204)
def unhide_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Ausblendung fuer den aktuellen Nutzer aufheben."""
    if not RecipesService(db).unhide(recipe_id):
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    db.commit()


class RecipeGoalRanked(RecipeOut):
    goal_match: GoalMatchInfo = GoalMatchInfo()


@router.get("/goal-ranked", response_model=list[RecipeGoalRanked])
def get_goal_ranked_recipes(
    target_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """Return all recipes ranked by goal match for the target date."""
    d = target_date or date.today()
    svc = RecipesService(db)
    excluded = _get_excluded_ids(db)
    recipes = svc.list_all(excluded_ingredient_ids=excluded)

    lager = LagerAdapter()
    user_allergens = _get_user_allergens(db)
    engine = MealDecisionEngine(
        db, lager,
        excluded_ingredient_ids=set(excluded),
        user_allergens=user_allergens,
    )

    # Build day context
    day_context = None
    try:
        profile_svc = ProfileService(db)
        targets = profile_svc.derive_daily_targets()
        day_slots = list(
            db.execute(
                select(MealSlot).where(MealSlot.date == d)
            ).scalars().all()
        )
        day_context = DayNutritionContext(
            targets=targets,
            slot_count_total=max(len(day_slots), 3),
        )
        for s in day_slots:
            if s.status == "eaten" and s.planned_recipe:
                np = s.planned_recipe.nutrition_per_portion or {}
                day_context.add_planned(np)
    except Exception:
        pass

    results = []
    for r in recipes:
        out = _recipe_to_out(r)
        gm = engine.compute_goal_match(r, day_context)
        results.append(RecipeGoalRanked(
            **out.model_dump(),
            goal_match=gm,
        ))

    # Sort by goal_match_pct descending
    results.sort(key=lambda x: x.goal_match.goal_match_pct, reverse=True)
    return results


@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    svc = RecipesService(db)
    r = svc.get(recipe_id)
    if not r:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})
    return _recipe_to_out(r)


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: int, body: RecipeUpdate, db: Session = Depends(get_db)):
    svc = RecipesService(db)
    r = svc.update(recipe_id, body)
    if not r:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})
    db.commit()
    return _recipe_to_out(r)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    svc = RecipesService(db)
    if not svc.delete(recipe_id):
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})
    db.commit()
    return Response(status_code=204)


@router.post("", response_model=RecipeOut, status_code=201)
def create_recipe(body: RecipeCreate, db: Session = Depends(get_db)):
    sub = db.info.get("owner_sub")  # privat fuer den anlegenden Nutzer (Hybrid)
    r = Recipe(
        name=body.name,
        portions_default=body.portions_default,
        cook_time_min=body.cook_time_min,
        owner_sub=sub,
    )
    r.tags = body.tags
    if body.nutrition_per_portion:
        r.nutrition_per_portion = body.nutrition_per_portion.model_dump()
    db.add(r)
    db.flush()

    for ri_in in body.ingredients:
        if not db.get(Ingredient, ri_in.ingredient_id):
            raise DomainError(
                f"Zutat {ri_in.ingredient_id} nicht gefunden",
                {"ingredient_id": ri_in.ingredient_id},
            )
        ri = RecipeIngredient(
            recipe_id=r.id,
            ingredient_id=ri_in.ingredient_id,
            amount=ri_in.amount,
            unit=ri_in.unit,
            optional_bool=ri_in.optional_bool,
            owner_sub=sub,
        )
        ri.substitutes = ri_in.substitutes
        db.add(ri)

    db.commit()
    db.refresh(r)
    svc = RecipesService(db)
    return _recipe_to_out(svc.get(r.id))


# ---------------------------------------------------------------------------
# HTML UI routes (/rezepte)
# ---------------------------------------------------------------------------


@html_router.get("/search")
def recipes_search_json(
    q: str = Query("", description="Suchbegriff"),
    db: Session = Depends(get_db),
):
    """JSON recipe search for adhoc intake modal."""
    svc = RecipesService(db)
    excluded = _get_excluded_ids(db)
    if q:
        recipes = svc.filter(q=q, excluded_ingredient_ids=excluded)
    else:
        recipes = svc.list_all(excluded_ingredient_ids=excluded)
    return [_recipe_to_out(r) for r in recipes[:20]]


@html_router.get("", response_class=HTMLResponse)
def recipes_list_page(
    request: Request,
    q: str = Query("", description="Suchbegriff"),
    tags: str = Query("", description="kommagetrennte Tags"),
    max_time: int | None = Query(None, description="max Kochzeit"),
    max_kcal: float | None = Query(None, description="max kcal"),
    flash: str = Query("", alias="flash"),
    show_hidden: bool = Query(False, description="ausgeblendete Rezepte anzeigen"),
    db: Session = Depends(get_db),
):
    svc = RecipesService(db)
    excluded = _get_excluded_ids(db)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    has_filter = q or tag_list or max_time or max_kcal
    if has_filter:
        recipes = svc.filter(
            q=q, tags=tag_list, max_cook_time=max_time, max_kcal=max_kcal,
            excluded_ingredient_ids=excluded, include_hidden=show_hidden,
        )
    else:
        recipes = svc.list_all(
            excluded_ingredient_ids=excluded, include_hidden=show_hidden,
        )

    hidden_ids = svc.hidden_recipe_ids()

    # Build recipe output with ingredient categories for canvas
    items = []
    for r in recipes:
        out = _recipe_to_out(r)
        out.ingredient_categories = _ingredient_categories(r)
        if r.id in hidden_ids:
            out.hidden = True
        items.append(out)

    # Collect all unique tags for filter UI
    all_recipes = svc.list_all()
    all_tags = sorted({t for r in all_recipes for t in r.tags})

    # Collect allergen info per recipe for display
    allergen_map: dict[int, list[str]] = {}
    for r in recipes:
        recipe_allergens: set[str] = set()
        for ri in r.ingredients:
            if ri.ingredient and ri.ingredient.allergens:
                recipe_allergens.update(ri.ingredient.allergens)
        if recipe_allergens:
            allergen_map[r.id] = sorted(recipe_allergens)

    # Compute goal-match data if profile exists
    goal_match_map = {}
    try:
        lager = LagerAdapter()
        profile_svc = ProfileService(db)
        user_allergens = _get_user_allergens(db)
        targets = profile_svc.derive_daily_targets()
        if targets and targets.kcal > 0:
            engine = MealDecisionEngine(
                db, lager,
                excluded_ingredient_ids=set(excluded),
                user_allergens=user_allergens,
            )
            today = date.today()
            day_slots = list(
                db.execute(
                    select(MealSlot).where(MealSlot.date == today)
                ).scalars().all()
            )
            day_context = DayNutritionContext(
                targets=targets,
                slot_count_total=max(len(day_slots), 3),
            )
            for s in day_slots:
                if s.status == "eaten" and s.planned_recipe:
                    np = s.planned_recipe.nutrition_per_portion or {}
                    day_context.add_planned(np)
            for r in recipes:
                gm = engine.compute_goal_match(r, day_context)
                goal_match_map[r.id] = gm
    except Exception:
        pass

    return templates.TemplateResponse(request, "recipes_list.html", {
        "show_hidden": show_hidden,
        "hidden_count": len(hidden_ids),
        "request": request,
        "recipes": items,
        "q": q,
        "tags_active": tags,
        "max_time": max_time,
        "max_kcal": max_kcal,
        "all_tags": all_tags,
        "flash": flash,
        "active_nav": "recipes",
        "goal_match_map": goal_match_map,
        "allergen_map": allergen_map,
    })


@html_router.get("/neu", response_class=HTMLResponse)
def recipe_new_page(request: Request, db: Session = Depends(get_db)):
    all_ingredients = list(
        db.execute(select(Ingredient).order_by(Ingredient.name_canonical)).scalars().all()
    )
    return templates.TemplateResponse(request, "recipe_form.html", {
        "request": request,
        "all_ingredients": all_ingredients,
        "active_nav": "recipes",
    })


@html_router.post("", response_class=RedirectResponse)
async def recipe_create_from_form(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()

    name = form.get("name", "").strip()
    if not name:
        raise DomainError("Name ist erforderlich", {})

    portions_default = int(form.get("portions_default") or 1)
    cook_time_min = int(form.get("cook_time_min") or 15)
    tags_raw = form.get("tags", "")

    r = Recipe(name=name, portions_default=portions_default, cook_time_min=cook_time_min,
               owner_sub=db.info.get("owner_sub"))

    tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    r.tags = tag_list

    # Nutrition
    def _float_or_none(key: str) -> float | None:
        val = form.get(key)
        if val is None or val == "":
            return None
        return float(val)

    kcal = _float_or_none("nutrition_kcal")
    protein = _float_or_none("nutrition_protein_g")
    carbs = _float_or_none("nutrition_carbs_g")
    fat = _float_or_none("nutrition_fat_g")
    fiber = _float_or_none("nutrition_fiber_g")

    if any(v is not None for v in [kcal, protein, carbs, fat, fiber]):
        r.nutrition_per_portion = {
            "kcal": kcal or 0,
            "protein_g": protein or 0,
            "carbs_g": carbs or 0,
            "fat_g": fat or 0,
            "fiber_g": fiber or 0,
        }

    db.add(r)
    db.flush()

    # Ingredient array fields
    ing_ids = form.getlist("ing_id[]")
    ing_amounts = form.getlist("ing_amount[]")
    ing_units = form.getlist("ing_unit[]")
    ing_optionals = form.getlist("ing_optional[]")

    for idx, raw_id in enumerate(ing_ids):
        if not raw_id:
            continue
        ingredient_id = int(raw_id)
        if not db.get(Ingredient, ingredient_id):
            raise DomainError(
                f"Zutat {ingredient_id} nicht gefunden",
                {"ingredient_id": ingredient_id},
            )
        amount = float(ing_amounts[idx]) if idx < len(ing_amounts) and ing_amounts[idx] else 0
        unit = ing_units[idx] if idx < len(ing_units) else "g"
        optional = idx < len(ing_optionals) and ing_optionals[idx] == "1"

        ri = RecipeIngredient(
            recipe_id=r.id,
            ingredient_id=ingredient_id,
            amount=amount,
            unit=unit,
            optional_bool=optional,
            owner_sub=r.owner_sub,
        )
        db.add(ri)

    db.commit()

    return RedirectResponse(
        url=f"/rezepte/{r.id}?flash=Rezept+gespeichert",
        status_code=303,
    )


@html_router.get("/{recipe_id}/bearbeiten", response_class=HTMLResponse)
def recipe_edit_page(
    request: Request,
    recipe_id: int,
    db: Session = Depends(get_db),
):
    svc = RecipesService(db)
    r = svc.get(recipe_id)
    if not r:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})
    out = _recipe_to_out(r)
    all_ingredients = list(
        db.execute(select(Ingredient).order_by(Ingredient.name_canonical)).scalars().all()
    )
    return templates.TemplateResponse(request, "recipe_form.html", {
        "request": request,
        "all_ingredients": all_ingredients,
        "recipe": out,
        "edit_mode": True,
        "active_nav": "recipes",
    })


@html_router.post("/{recipe_id}/bearbeiten", response_class=RedirectResponse)
async def recipe_update_from_form(
    request: Request,
    recipe_id: int,
    db: Session = Depends(get_db),
):
    form = await request.form()

    name = form.get("name", "").strip()
    if not name:
        raise DomainError("Name ist erforderlich", {})

    portions_default = int(form.get("portions_default") or 1)
    cook_time_min = int(form.get("cook_time_min") or 15)
    tags_raw = form.get("tags", "")
    instructions = form.get("instructions", "").strip() or None

    svc = RecipesService(db)
    recipe = svc.get(recipe_id)
    if not recipe:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})

    recipe.name = name
    recipe.portions_default = portions_default
    recipe.cook_time_min = cook_time_min
    recipe.instructions = instructions

    tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    recipe.tags = tag_list

    # Nutrition
    def _float_or_none(key: str) -> float | None:
        val = form.get(key)
        if val is None or val == "":
            return None
        return float(val)

    kcal = _float_or_none("nutrition_kcal")
    protein = _float_or_none("nutrition_protein_g")
    carbs = _float_or_none("nutrition_carbs_g")
    fat = _float_or_none("nutrition_fat_g")
    fiber = _float_or_none("nutrition_fiber_g")

    if any(v is not None for v in [kcal, protein, carbs, fat, fiber]):
        recipe.nutrition_per_portion = {
            "kcal": kcal or 0,
            "protein_g": protein or 0,
            "carbs_g": carbs or 0,
            "fat_g": fat or 0,
            "fiber_g": fiber or 0,
        }

    # Replace ingredients
    for ri in list(recipe.ingredients):
        db.delete(ri)
    db.flush()

    ing_ids = form.getlist("ing_id[]")
    ing_amounts = form.getlist("ing_amount[]")
    ing_units = form.getlist("ing_unit[]")
    ing_optionals = form.getlist("ing_optional[]")

    for idx, raw_id in enumerate(ing_ids):
        if not raw_id:
            continue
        ingredient_id = int(raw_id)
        if not db.get(Ingredient, ingredient_id):
            raise DomainError(
                f"Zutat {ingredient_id} nicht gefunden",
                {"ingredient_id": ingredient_id},
            )
        amount = float(ing_amounts[idx]) if idx < len(ing_amounts) and ing_amounts[idx] else 0
        unit = ing_units[idx] if idx < len(ing_units) else "g"
        optional = idx < len(ing_optionals) and ing_optionals[idx] == "1"

        ri = RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ingredient_id,
            amount=amount,
            unit=unit,
            owner_sub=recipe.owner_sub,
            optional_bool=optional,
        )
        db.add(ri)

    db.commit()

    return RedirectResponse(
        url=f"/rezepte/{recipe_id}?flash=Rezept+aktualisiert",
        status_code=303,
    )


@html_router.post("/{recipe_id}/loeschen", response_class=RedirectResponse)
def recipe_delete_from_form(
    recipe_id: int,
    db: Session = Depends(get_db),
):
    svc = RecipesService(db)
    if not svc.delete(recipe_id):
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})
    db.commit()
    return RedirectResponse(
        url="/rezepte?flash=Rezept+geloescht",
        status_code=303,
    )


@html_router.get("/{recipe_id}", response_class=HTMLResponse)
def recipe_detail_page(
    request: Request,
    recipe_id: int,
    flash: str = Query("", alias="flash"),
    db: Session = Depends(get_db),
):
    svc = RecipesService(db)
    r = svc.get(recipe_id)
    if not r:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})
    out = _recipe_to_out(r)
    ingredients = []
    recipe_allergens: set[str] = set()
    for ri in r.ingredients:
        ing = ri.ingredient
        ing_allergens = ing.allergens if ing else []
        ingredients.append({
            "name": ing.name_canonical if ing else f"#{ri.ingredient_id}",
            "amount": ri.amount,
            "unit": ri.unit,
            "optional": ri.optional_bool,
            "allergens": ing_allergens,
        })
        if ing_allergens:
            recipe_allergens.update(ing_allergens)
    return templates.TemplateResponse(request, "recipe_detail.html", {
        "request": request,
        "recipe": out,
        "ingredients": ingredients,
        "ingredient_categories": _ingredient_categories(r),
        "recipe_allergens": sorted(recipe_allergens),
        "flash": flash,
        "active_nav": "recipes",
    })


# ---------------------------------------------------------------------------
# HTML UI routes (/zutaten): Ingredient allergen management
# ---------------------------------------------------------------------------


@ingredients_html_router.get("", response_class=HTMLResponse)
def ingredients_list_page(
    request: Request,
    flash: str = Query("", alias="flash"),
    db: Session = Depends(get_db),
):
    ingredients = list(
        db.execute(
            select(Ingredient).order_by(Ingredient.name_canonical)
        ).scalars().all()
    )
    return templates.TemplateResponse(request, "ingredients_list.html", {
        "request": request,
        "ingredients": ingredients,
        "flash": flash,
        "active_nav": "recipes",
    })


@ingredients_html_router.get("/{ingredient_id}/allergene", response_class=HTMLResponse)
def ingredient_allergens_page(
    request: Request,
    ingredient_id: int,
    flash: str = Query("", alias="flash"),
    db: Session = Depends(get_db),
):
    ing = db.get(Ingredient, ingredient_id)
    if not ing:
        raise DomainError("Zutat nicht gefunden", {"ingredient_id": ingredient_id})
    return templates.TemplateResponse(request, "ingredient_allergens.html", {
        "request": request,
        "ingredient": ing,
        "eu14_allergens": EU14_ALLERGENS,
        "flash": flash,
        "active_nav": "recipes",
    })


@ingredients_html_router.post("/{ingredient_id}/allergene", response_class=RedirectResponse)
async def ingredient_allergens_update(
    request: Request,
    ingredient_id: int,
    db: Session = Depends(get_db),
):
    ing = db.get(Ingredient, ingredient_id)
    if not ing:
        raise DomainError("Zutat nicht gefunden", {"ingredient_id": ingredient_id})
    form = await request.form()
    allergens = [x for x in form.getlist("allergens[]") if x]
    ing.allergens = allergens
    db.commit()
    return RedirectResponse(
        url=f"/zutaten/{ingredient_id}/allergene?flash=Allergene+gespeichert",
        status_code=303,
    )
