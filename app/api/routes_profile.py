"""Profile routes: user profile, TDEE/macro targets, body metrics."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    BodyMetricCreate,
    BodyMetricOut,
    DailyMacroTargets,
    TDEEOut,
    UserProfileOut,
    UserProfileUpdate,
)
from app.services.profile import ACTIVITY_MULTIPLIERS, ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserProfileOut)
def get_profile(db: Session = Depends(get_db)):
    svc = ProfileService(db)
    p = svc.get_or_create()
    db.commit()
    return _profile_out(p)


@router.put("", response_model=UserProfileOut)
def update_profile(body: UserProfileUpdate, db: Session = Depends(get_db)):
    svc = ProfileService(db)
    data = body.model_dump(exclude_unset=True)
    p = svc.update(data)
    db.commit()
    return _profile_out(p)


@router.get("/tdee", response_model=TDEEOut)
def get_tdee(db: Session = Depends(get_db)):
    svc = ProfileService(db)
    p = svc.get_or_create()
    db.commit()
    bmr = svc.calc_bmr(p)
    tdee = svc.calc_tdee(p)
    mult = ACTIVITY_MULTIPLIERS.get(p.activity_level, 1.55)
    return TDEEOut(
        bmr=round(bmr, 1),
        tdee=round(tdee, 1),
        activity_level=p.activity_level,
        multiplier=mult,
    )


@router.get("/targets", response_model=DailyMacroTargets)
def get_targets(
    tag: date | None = Query(
        default=None,
        description=(
            "Tagesbezogene Ziele fuer dieses Datum. Ohne Angabe das statische "
            "Ziel wie bisher (fitness wird dann nicht gefragt)."
        ),
    ),
    db: Session = Depends(get_db),
):
    """Kalorien- und Makroziele.

    ★ Ohne ``tag`` bleibt es beim bisherigen Verhalten. Das ist Absicht: der
    fitness-Adapter in fitness ruft diesen Pfad, und ein stiller Wechsel auf
    eine Tagesrechnung wuerde dort eine Frage beantworten, die niemand
    gestellt hat.
    """
    svc = ProfileService(db)
    if tag is None:
        return svc.derive_daily_targets()
    ziele, _grund = svc.tagesziele(tag)
    return ziele


@router.post("/metrics", response_model=BodyMetricOut, status_code=201)
def add_metric(body: BodyMetricCreate, db: Session = Depends(get_db)):
    svc = ProfileService(db)
    bm = svc.add_body_metric(
        weight_kg=body.weight_kg,
        metric_date=body.metric_date,
        body_fat_pct=body.body_fat_pct,
        waist_cm=body.waist_cm,
    )
    db.commit()
    return BodyMetricOut(
        id=bm.id,
        date=bm.date,
        weight_kg=bm.weight_kg,
        body_fat_pct=bm.body_fat_pct,
        waist_cm=bm.waist_cm,
    )


@router.get("/metrics", response_model=list[BodyMetricOut])
def list_metrics(limit: int = Query(90, ge=1, le=365), db: Session = Depends(get_db)):
    svc = ProfileService(db)
    metrics = svc.get_metrics(limit=limit)
    return [
        BodyMetricOut(
            id=m.id,
            date=m.date,
            weight_kg=m.weight_kg,
            body_fat_pct=m.body_fat_pct,
            waist_cm=m.waist_cm,
        )
        for m in metrics
    ]


def _profile_out(p) -> UserProfileOut:
    return UserProfileOut(
        id=p.id,
        height_cm=p.height_cm,
        weight_kg=p.weight_kg,
        birth_date=p.birth_date,
        sex=p.sex,
        body_fat_pct=p.body_fat_pct,
        activity_level=p.activity_level,
        waist_cm=p.waist_cm,
        allergies=p.allergies,
        intolerances=p.intolerances,
        target_weight_kg=p.target_weight_kg,
        kcal_target_override=p.kcal_target_override,
        excluded_ingredient_ids=p.excluded_ingredient_ids,
    )
