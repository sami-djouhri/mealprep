"""Shopping list routes."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    EinkaufAbhaken,
    EinkaufAbhakenAntwort,
    ShoppingLineOut,
    ShoppingListOut,
)
from app.services.shopping import ShoppingService

router = APIRouter(prefix="/shopping", tags=["shopping"])
templates = Jinja2Templates(directory="app/templates")


@router.post("/generate", response_model=ShoppingListOut)
def generate_shopping(days: int = Query(3, ge=1, le=90), db: Session = Depends(get_db)):
    svc = ShoppingService(db)
    sl = svc.generate_for_window(date.today(), days)
    return _list_out(sl, db, svc)


@router.get("/current", response_model=ShoppingListOut | None)
def get_current_json(db: Session = Depends(get_db)):
    svc = ShoppingService(db)
    sl = svc.get_current()
    if not sl:
        return None
    return _list_out(sl, db, svc)


@router.post("/lines/{line_id}/gekauft", response_model=EinkaufAbhakenAntwort)
def zeile_abhaken(
    line_id: int,
    body: EinkaufAbhaken | None = None,
    db: Session = Depends(get_db),
):
    """Eine Zeile als gekauft markieren und in den Lager-Bestand buchen.

    Hier schliesst sich der Kreis: bis 2026-09-13 buchte mealprep beim Kochen
    ab und nie wieder auf, der rechnerische Bestand lief gegen null.
    """
    body = body or EinkaufAbhaken()
    svc = ShoppingService(db)
    line = svc.abhaken(
        line_id,
        menge=body.menge,
        mhd=body.mhd.isoformat() if body.mhd else None,
        ort=body.ort,
    )
    zutat = line.ingredient
    return EinkaufAbhakenAntwort(
        line_id=line.id,
        ingredient_name=zutat.name_canonical if zutat else "",
        gekaufte_menge=line.gekaufte_menge,
        unit=line.unit,
        gekauft_am=line.gekauft_am,
        lager_stock_entry_id=line.lager_stock_entry_id,
    )


@router.delete("/lines/{line_id}/gekauft", response_model=EinkaufAbhakenAntwort)
def zeile_haken_zuruecknehmen(line_id: int, db: Session = Depends(get_db)):
    """Haken zuruecknehmen und den erzeugten Bestandseintrag entfernen."""
    svc = ShoppingService(db)
    line = svc.haken_zuruecknehmen(line_id)
    zutat = line.ingredient
    return EinkaufAbhakenAntwort(
        line_id=line.id,
        ingredient_name=zutat.name_canonical if zutat else "",
        gekaufte_menge=None,
        unit=line.unit,
        gekauft_am=None,
        lager_stock_entry_id=None,
    )


@router.get("/current/view", response_class=HTMLResponse)
def shopping_view(request: Request, db: Session = Depends(get_db)):
    svc = ShoppingService(db)
    sl = svc.get_current()
    lines: list[dict] = []
    offen = 0
    unverknuepft = 0
    bestand_unbekannt = False
    if sl:
        try:
            strategic_map = svc.compute_strategic_info(date.today(), days_ahead=3)
        except Exception:
            strategic_map = {}

        for z in svc.zeilen_mit_restbedarf(sl):
            z = dict(z)
            z["name"] = z["ingredient_name"] or f"#{z['ingredient_id']}"
            z["reasons"] = z["reason_codes"]
            z["packs"] = z["suggested_packs"]
            z["strategic"] = strategic_map.get(z["ingredient_id"])
            lines.append(z)
            if z["gekauft_am"] is None and z["noch_noetig"] > 0:
                offen += 1
            if not z["verknuepft"]:
                unverknuepft += 1
            bestand_unbekannt = bestand_unbekannt or z["bestand_unbekannt"]

    return templates.TemplateResponse(request, "shopping.html", {
        "request": request,
        "shopping": sl,
        "lines": lines,
        "offen": offen,
        "unverknuepft": unverknuepft,
        "bestand_unbekannt": bestand_unbekannt,
        "active_nav": "shopping",
    })


def _list_out(sl, db: Session, svc: ShoppingService | None = None) -> ShoppingListOut:
    svc = svc or ShoppingService(db)
    try:
        strategic_map = svc.compute_strategic_info(date.today(), days_ahead=3)
    except Exception:
        strategic_map = {}

    lines = [
        ShoppingLineOut(
            id=z["id"],
            ingredient_id=z["ingredient_id"],
            ingredient_name=z["ingredient_name"],
            needed_amount=z["geplant"],
            bedarf_brutto=z["bedarf_brutto"],
            noch_noetig=z["noch_noetig"],
            unit=z["unit"],
            suggested_packs=z["suggested_packs"],
            reason_codes=z["reason_codes"],
            strategic_info=strategic_map.get(z["ingredient_id"]),
            gekauft_am=z["gekauft_am"],
            gekaufte_menge=z["gekaufte_menge"],
            verknuepft=z["verknuepft"],
            bestand_unbekannt=z["bestand_unbekannt"],
        )
        for z in svc.zeilen_mit_restbedarf(sl)
    ]
    return ShoppingListOut(
        id=sl.id,
        created_at=sl.created_at,
        status=sl.status,
        lines=lines,
    )
