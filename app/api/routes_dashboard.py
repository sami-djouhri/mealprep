"""Dashboard route: SPA onepager + profile page."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Ingredient
from app.services.profile import ProfileService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# EU-14 Hauptallergene (Verordnung (EU) Nr. 1169/2011)
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


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Serve the SPA onepager."""
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "active_nav": "dashboard",
    })


# ----- Profile page (HTML) -----


@router.get("/profil", response_class=HTMLResponse)
def profile_page(
    request: Request,
    flash: str = Query("", alias="flash"),
    db: Session = Depends(get_db),
):
    svc = ProfileService(db)
    p = svc.get_or_create()
    db.commit()

    bmr = svc.calc_bmr(p)
    tdee = svc.calc_tdee(p)
    targets = svc.derive_daily_targets()

    all_ingredients = list(
        db.execute(select(Ingredient).order_by(Ingredient.name_canonical)).scalars().all()
    )

    # Goal phase and statement
    goal_phase_label = "Gewicht halten"
    goal_phase_class = "phase-maintain"
    goal_statement = ""
    deficit_or_surplus = ""

    if p.target_weight_kg is not None and p.target_weight_kg < p.weight_kg - 1:
        goal_phase_label = "Definitionsphase"
        goal_phase_class = "phase-cut"
        deficit = round(tdee - targets.kcal, 0)
        goal_statement = (
            f"Du isst {int(targets.kcal)} kcal pro Tag, um dein "
            f"Zielgewicht von {p.target_weight_kg:.0f} kg zu erreichen."
        )
        deficit_or_surplus = f"{int(deficit)} kcal Defizit pro Tag"
    elif p.target_weight_kg is not None and p.target_weight_kg > p.weight_kg + 1:
        goal_phase_label = "Aufbauphase"
        goal_phase_class = "phase-bulk"
        surplus = round(targets.kcal - tdee, 0)
        goal_statement = (
            f"Du isst {int(targets.kcal)} kcal pro Tag, um auf "
            f"{p.target_weight_kg:.0f} kg aufzubauen."
        )
        deficit_or_surplus = f"{int(surplus)} kcal Ueberschuss pro Tag"
    else:
        goal_statement = f"Du isst {int(targets.kcal)} kcal pro Tag, um dein Gewicht zu halten."
        deficit_or_surplus = "Ausgeglichene Energiebilanz"

    # Macro split percentages for visual bar
    total_kcal = targets.kcal or 1
    protein_pct = round((targets.protein_g * 4 / total_kcal) * 100)
    fat_pct = round((targets.fat_g * 9 / total_kcal) * 100)
    carbs_pct = 100 - protein_pct - fat_pct

    return templates.TemplateResponse(request, "profile.html", {
        "request": request,
        "profile": p,
        "bmr": round(bmr, 1),
        "tdee": round(tdee, 1),
        "targets": targets,
        "all_ingredients": all_ingredients,
        "eu14_allergens": EU14_ALLERGENS,
        "flash": flash,
        "active_nav": "profile",
        "goal_phase_label": goal_phase_label,
        "goal_phase_class": goal_phase_class,
        "goal_statement": goal_statement,
        "deficit_or_surplus": deficit_or_surplus,
        "protein_pct": protein_pct,
        "carbs_pct": carbs_pct,
        "fat_pct": fat_pct,
    })


@router.post("/profil/koerperdaten", response_class=RedirectResponse)
async def profile_update_body(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()

    def _float_or_none(key: str) -> float | None:
        val = form.get(key)
        if val is None or val == "":
            return None
        return float(val)

    def _int_or_none(key: str) -> int | None:
        val = form.get(key)
        if val is None or val == "":
            return None
        return int(val)

    data: dict = {}

    height = _float_or_none("height_cm")
    if height is not None:
        data["height_cm"] = height

    weight = _float_or_none("weight_kg")
    if weight is not None:
        data["weight_kg"] = weight

    sex = form.get("sex")
    if sex:
        data["sex"] = sex

    birth_date_str = form.get("birth_date", "").strip()
    if birth_date_str:
        from datetime import date as date_type
        data["birth_date"] = date_type.fromisoformat(birth_date_str)

    data["body_fat_pct"] = _float_or_none("body_fat_pct")
    data["waist_cm"] = _float_or_none("waist_cm")

    activity = form.get("activity_level")
    if activity:
        data["activity_level"] = activity

    data["target_weight_kg"] = _float_or_none("target_weight_kg")
    data["kcal_target_override"] = _int_or_none("kcal_target_override")

    # Allergies & intolerances (checkbox arrays)
    allergies = [x for x in form.getlist("allergies[]") if x]
    intolerances = [x for x in form.getlist("intolerances[]") if x]
    data["allergies"] = allergies
    data["intolerances"] = intolerances

    svc = ProfileService(db)
    svc.update(data)
    db.commit()
    return RedirectResponse(
        url="/profil?flash=Profil+gespeichert",
        status_code=303,
    )


@router.post("/profil/ausschluesse", response_class=RedirectResponse)
async def profile_update_exclusions(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    excluded_ids = [int(x) for x in form.getlist("excluded_ids[]") if x]
    svc = ProfileService(db)
    svc.update({"excluded_ingredient_ids": excluded_ids})
    db.commit()
    return RedirectResponse(
        url="/profil?flash=Ausschluesse+gespeichert",
        status_code=303,
    )
