"""Multi-Tenant-Scoping auf ORM-Ebene (fail-closed), analog lager/fitness.

STRICT: owner_sub == sub (before_flush stempelt neue Objekte).
HYBRID (recipe/recipe_ingredient): owner_sub NULL = globale Bibliothek (fuer alle),
sonst privat. Read-Praedikat: owner_sub IS NULL OR owner_sub == sub. NICHT auto-
gestempelt (Seeds bleiben NULL; User-Rezepte setzen owner_sub in der Create-Route).
ingredient bleibt GLOBAL (Katalog). sub aus session.info["owner_sub"] (get_db).
"""

from sqlalchemy import event, or_
from sqlalchemy.orm import with_loader_criteria

from app.config import settings
from app.db import SessionLocal
from app.models import (
    BodyMetric,
    GoalPhase,
    IntakeItem,
    MealSlot,
    Recipe,
    RecipeHidden,
    RecipeIngredient,
    ShoppingList,
    ShoppingListLine,
    ShoppingRule,
    Supplement,
    SupplementLog,
    UserProfile,
)

STRICT_MODELS = (
    GoalPhase, BodyMetric, UserProfile, MealSlot, IntakeItem,
    ShoppingRule, ShoppingList, ShoppingListLine, Supplement, SupplementLog,
    RecipeHidden,
)
HYBRID_MODELS = (Recipe, RecipeIngredient)


def _session_sub(session) -> str:
    return session.info.get("owner_sub") or settings.DEFAULT_OWNER_SUB


@event.listens_for(SessionLocal, "do_orm_execute")
def _apply_tenant_scope(execute_state) -> None:
    if not execute_state.is_select or execute_state.execution_options.get("skip_tenant"):
        return
    sub = _session_sub(execute_state.session)
    for model in STRICT_MODELS:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(model, lambda cls: cls.owner_sub == sub, include_aliases=True)
        )
    for model in HYBRID_MODELS:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                model, lambda cls: or_(cls.owner_sub.is_(None), cls.owner_sub == sub),
                include_aliases=True,
            )
        )


@event.listens_for(SessionLocal, "before_flush")
def _stamp_tenant(session, _flush_context, _instances) -> None:
    sub = _session_sub(session)
    for obj in session.new:
        # HYBRID absichtlich NICHT stempeln (Seed=global NULL, Route setzt sub selbst).
        if isinstance(obj, STRICT_MODELS) and not getattr(obj, "owner_sub", None):
            obj.owner_sub = sub
