"""Inventory routes: ingredients + Lager-mapping + feasibility check."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.domain import DomainError
from app.models import Ingredient, Recipe, RecipeIngredient
from app.schemas import (
    FeasibilityItem,
    FeasibilityResult,
    IngredientCreate,
    IngredientOut,
    LagerAbgleichAntwort,
    LagerAbgleichUebernahme,
    LagerAbgleichVorschlag,
    LinkLagerRequest,
)
from app.services import lager_abgleich
from app.services.lager_adapter import LagerAdapter, LagerUnavailable

router = APIRouter(prefix="/inventory", tags=["inventory"])


# ----- Ingredients -----

@router.get("/ingredients", response_model=list[IngredientOut])
def list_ingredients(db: Session = Depends(get_db)):
    rows = db.execute(select(Ingredient)).scalars().all()
    return [_ing_out(i) for i in rows]


@router.post("/ingredients", response_model=IngredientOut, status_code=201)
def create_ingredient(body: IngredientCreate, db: Session = Depends(get_db)):
    ing = Ingredient(
        name_canonical=body.name_canonical,
        category=body.category,
        default_unit=body.default_unit,
        shelf_life_type=body.shelf_life_type,
        lager_product_id=body.lager_product_id,
    )
    if body.nutrition_per_100:
        ing.nutrition_per_100 = body.nutrition_per_100.model_dump()
    ing.typical_pack_sizes = body.typical_pack_sizes
    ing.synonyms = body.synonyms
    ing.allergens = body.allergens
    db.add(ing)
    db.commit()
    db.refresh(ing)
    return _ing_out(ing)


# ----- Lager linking -----

@router.put("/ingredients/{ingredient_id}/link-lager", response_model=IngredientOut)
def link_lager(ingredient_id: int, body: LinkLagerRequest, db: Session = Depends(get_db)):
    """Eine Zutat mit einem Lager-Produkt verknuepfen.

    Geprueft wird wie bei der Sammeluebernahme, dass es das Produkt drueben
    gibt: eine Nummer ins Leere faellt sonst nirgends auf, sie liefert nur
    dauerhaft Bestand 0.
    """
    ing = db.get(Ingredient, ingredient_id)
    if not ing:
        raise DomainError("Zutat nicht gefunden", {"ingredient_id": ingredient_id})
    try:
        bekannte = lager_abgleich.bekannte_produkt_ids(LagerAdapter())
    except LagerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if bekannte is not None and body.lager_product_id not in bekannte:
        raise DomainError(
            "Dieses Produkt gibt es im Lager nicht",
            {"lager_product_id": body.lager_product_id},
        )
    ing.lager_product_id = body.lager_product_id
    db.commit()
    db.refresh(ing)
    return _ing_out(ing)


@router.get("/ingredients/{ingredient_id}/stock")
def ingredient_stock(ingredient_id: int, db: Session = Depends(get_db)):
    ing = db.get(Ingredient, ingredient_id)
    if not ing:
        raise DomainError("Zutat nicht gefunden", {"ingredient_id": ingredient_id})
    if not ing.lager_product_id:
        return {"ingredient_id": ingredient_id, "lager_product_id": None, "available": 0.0, "unit": ing.default_unit}
    lager = LagerAdapter()
    available = lager.get_available(ing.lager_product_id, ing.default_unit)
    return {
        "ingredient_id": ingredient_id,
        "lager_product_id": ing.lager_product_id,
        "available": available,
        "unit": ing.default_unit,
    }


# ----- Feasibility check -----

@router.get("/recipes/{recipe_id}/feasibility", response_model=FeasibilityResult)
def check_feasibility(recipe_id: int, portions: int = 1, db: Session = Depends(get_db)):
    recipe = db.execute(
        select(Recipe)
        .options(joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient))
        .where(Recipe.id == recipe_id)
    ).unique().scalar_one_or_none()
    if not recipe:
        raise DomainError("Rezept nicht gefunden", {"recipe_id": recipe_id})

    lager = LagerAdapter()
    # Ein Schnappschuss statt eines Aufrufs je Zutat des Rezepts.
    lager.schnappschuss_laden()
    items: list[FeasibilityItem] = []
    all_sufficient = True
    for ri in recipe.ingredients:
        if ri.optional_bool:
            continue
        ing = ri.ingredient
        needed = ri.amount * portions
        lager_pid = ing.lager_product_id if ing else None
        available = lager.get_available(lager_pid, ri.unit) if lager_pid else 0.0
        sufficient = available >= needed - 0.001
        if not sufficient:
            all_sufficient = False
        items.append(FeasibilityItem(
            ingredient_id=ri.ingredient_id,
            ingredient_name=ing.name_canonical if ing else "",
            lager_product_id=lager_pid,
            needed=round(needed, 1),
            unit=ri.unit,
            available=round(available, 1),
            sufficient=sufficient,
        ))

    return FeasibilityResult(
        recipe_id=recipe.id,
        recipe_name=recipe.name,
        feasible=all_sufficient,
        items=items,
    )


# ----- helpers -----

def _ing_out(i: Ingredient) -> IngredientOut:
    return IngredientOut(
        id=i.id,
        name_canonical=i.name_canonical,
        category=i.category,
        default_unit=i.default_unit,
        nutrition_per_100=i.nutrition_per_100 or None,
        typical_pack_sizes=i.typical_pack_sizes,
        shelf_life_type=i.shelf_life_type,
        allergens=i.allergens,
        lager_product_id=i.lager_product_id,
    )


# ----- Lager-Abgleich -----
#
# ★ Gemessen am 2026-09-12: null von 47 Zutaten waren mit einem Lager-Produkt
# verknuepft, bei 45 Rezepten und 679 geplanten Mahlzeiten. Damit lieferte
# ``get_available`` ueberall 0, die Machbarkeit jedes Rezepts war "nichts da",
# und die Einkaufsliste zog den Vorrat nie ab. Der Adapter haengt an zehn
# Stellen und trug trotzdem nichts, weil die eine Verbindung fehlte, die von
# Hand haette gesetzt werden muessen.


@router.get("/lager-abgleich", response_model=LagerAbgleichAntwort)
def lager_abgleich_vorschlagen(db: Session = Depends(get_db)):
    """Unverknuepfte Zutaten gegen die Lager-Produkte halten."""
    adapter = LagerAdapter()
    unverknuepft = len(db.execute(
        select(Ingredient).where(Ingredient.lager_product_id.is_(None))
    ).scalars().all())

    if not adapter.available:
        # Leere Liste heisst sonst "nichts zuzuordnen", und das waere eine
        # Aussage, die hier niemand treffen kann.
        return LagerAbgleichAntwort(
            vorschlaege=[], unverknuepft_gesamt=unverknuepft, lager_erreichbar=False,
        )

    gefunden = lager_abgleich.vorschlaege(db, adapter)
    return LagerAbgleichAntwort(
        vorschlaege=[LagerAbgleichVorschlag(**v.__dict__) for v in gefunden],
        unverknuepft_gesamt=unverknuepft,
        lager_erreichbar=True,
    )


@router.post("/lager-abgleich", response_model=list[IngredientOut])
def lager_abgleich_uebernehmen(
    body: LagerAbgleichUebernahme, db: Session = Depends(get_db),
):
    """Bestaetigte Paare verknuepfen. Bestehende Zuordnungen bleiben.

    503 statt einer leeren Liste, wenn lager nicht antwortet: die Paare werden
    gegen den Produktkatalog geprueft, und ohne ihn ist "nichts uebernommen"
    von "nichts passte" nicht zu unterscheiden.
    """
    try:
        geaendert = lager_abgleich.uebernehmen(
            db, [(p.ingredient_id, p.lager_product_id) for p in body.paare],
        )
    except LagerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    for zutat in geaendert:
        db.refresh(zutat)
    return [_ing_out(z) for z in geaendert]
