"""Planning service: local slot management and meal planning."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import MealSlot, GoalPhase, Recipe, RecipeIngredient
from app.schemas import DayNutritionContext, DecisionResult, MealSlotOut, PlanDayResult
from app.services.kalender_adapter import KalenderAdapter
from app.services.lager_adapter import LagerAdapter
from app.services.meal_decision import MealDecisionEngine
from app.services.profile import ProfileService
from app.services.shopping import ShoppingService

log = logging.getLogger(__name__)


class PlanningService:
    def __init__(
        self,
        db: Session,
        lager: LagerAdapter | None = None,
        kalender: KalenderAdapter | None = None,
    ):
        self.db = db
        self.lager = lager or LagerAdapter()
        self.kalender = kalender or KalenderAdapter()
        self.profile_svc = ProfileService(db)
        # Load excluded ingredient IDs and allergens from user profile
        profile = self.profile_svc.get_or_create()
        self._excluded_ids: set[int] = set(profile.excluded_ingredient_ids)
        self._user_allergens: set[str] = {
            a.lower() for a in (profile.allergies + profile.intolerances)
        }
        self.engine = MealDecisionEngine(
            db, self.lager,
            excluded_ingredient_ids=self._excluded_ids,
            user_allergens=self._user_allergens,
        )

    def plan_day(self, target_date: date) -> PlanDayResult:
        """Ensure slots exist, decide recipes using Lager availability.

        Respects pinned slots: they keep their recipe and contribute to
        the day's nutrition context but are not re-planned.
        """
        slots = self._ensure_default_slots(target_date)

        phase = self.db.execute(
            select(GoalPhase).where(GoalPhase.is_active.is_(True))
        ).scalar_one_or_none()

        # Build day-aware nutrition context from profile
        targets = self.profile_svc.derive_daily_targets()
        all_slots = [s for s in slots if s.status != "eaten"]
        day_context = DayNutritionContext(
            targets=targets,
            slot_count_total=len(all_slots) or 1,
            slot_index=0,
        )

        # Pre-fill context with nutrition from eaten and pinned slots
        for slot in slots:
            if slot.status == "eaten" or slot.pinned:
                if slot.planned_recipe_id:
                    recipe = self.db.get(Recipe, slot.planned_recipe_id)
                    if recipe and recipe.nutrition_per_portion:
                        day_context.add_planned(recipe.nutrition_per_portion)

        decisions: list[DecisionResult] = []
        used_recipe_ids: set[int] = set()
        # Collect already-used recipe IDs from pinned/eaten slots
        for slot in slots:
            if (slot.pinned or slot.status == "eaten") and slot.planned_recipe_id:
                used_recipe_ids.add(slot.planned_recipe_id)

        for slot in slots:
            if slot.status == "eaten" or slot.pinned:
                continue
            result = self.engine.decide_best_for_slot(
                slot, phase,
                exclude_recipe_ids=used_recipe_ids,
                day_context=day_context,
            )
            if result:
                slot.planned_recipe_id = result.selected_recipe_id
                used_recipe_ids.add(result.selected_recipe_id)
                decisions.append(result)
                # Reserve ingredients so subsequent days see reduced stock
                recipe = self.db.get(Recipe, result.selected_recipe_id)
                if recipe:
                    if recipe.nutrition_per_portion:
                        day_context.add_planned(recipe.nutrition_per_portion)
                    self.engine.reserve_recipe(recipe)

        self.db.commit()

        # Auto-refresh shopping list after planning
        try:
            shopping_svc = ShoppingService(self.db, self.lager)
            shopping_svc.auto_refresh(target_date)
        except Exception as exc:
            log.warning("Auto-refresh Einkaufsliste fehlgeschlagen: %s", exc)

        slot_outs = [self._slot_to_out(s) for s in slots]
        return PlanDayResult(date=target_date, decisions=decisions, slots=slot_outs)

    def plan_range(self, start_date: date, days: int | None = None) -> None:
        """Plan multiple days with cross-day ingredient reservations.

        Tracks ingredient usage across all days so the decision engine
        sees reduced stock for later days (no over-planning).
        After main slots, auto-snacks fill remaining macro deficits.
        """
        days = days or settings.PLAN_HORIZON_DAYS
        reservations: dict[tuple[int, str], float] = {}

        # Plan-Signatur VOR den Passes erfassen (query-basiert, robust gegen die
        # flush()-Aufrufe der Passes; session.dirty waere hier unzuverlaessig).
        plan_before = self._range_plan_fingerprint(start_date, days)

        # Pass 1: ensure slots exist and collect reservations from
        # already-planned/pinned/eaten slots
        for i in range(days):
            d = start_date + timedelta(days=i)
            slots = self._ensure_default_slots(d)
            for s in slots:
                if s.planned_recipe_id and (s.pinned or s.status == "eaten"):
                    self._add_recipe_reservations(reservations, s.planned_recipe_id)

        # Pass 2: plan unplanned slots day-by-day with shared reservations
        phase = self.db.execute(
            select(GoalPhase).where(GoalPhase.is_active.is_(True))
        ).scalar_one_or_none()

        for i in range(days):
            d = start_date + timedelta(days=i)
            slots = self._get_local_slots(d)
            needs_planning = any(
                s.planned_recipe_id is None and s.status != "eaten" and not s.pinned
                for s in slots
            )
            if needs_planning:
                self._plan_day_with_reservations(d, reservations, phase)

        # Pass 3: auto-snacks for each day
        for i in range(days):
            d = start_date + timedelta(days=i)
            self._maybe_add_snacks(d, reservations, phase)

        self.db.commit()

        # Einkaufsliste nur neu bauen, wenn sich der Plan im Bereich wirklich
        # geaendert hat. Ein reiner Read-Poll aufs Dashboard (life-ops pollt
        # /dashboard) ruft plan_range auf, hat im Steady-State aber nichts zu
        # planen, dann darf auto_refresh keine neue Einkaufsliste erzeugen/
        # schliessen (Wurzel des I5-Runaways). Shopping ist plan-abgeleitet:
        # unveraenderter Plan => unveraenderte Liste.
        if self._range_plan_fingerprint(start_date, days) != plan_before:
            # Refresh shopping for the full range
            try:
                shopping_svc = ShoppingService(self.db, self.lager)
                shopping_svc.auto_refresh(start_date, days_ahead=days)
            except Exception as exc:
                log.warning("Auto-refresh Einkaufsliste (range) fehlgeschlagen: %s", exc)

    def _range_plan_fingerprint(self, start_date: date, days: int) -> tuple:
        """Signatur des Plans im Bereich [start_date, +days): je Slot
        (date, slot_type, planned_recipe_id, status). Query-basiert, damit sie
        die von den Passes ge-flushten (uncommitteten) Aenderungen sieht,
        anders als session.dirty, das die flush()-Aufrufe leeren. Aendert sich
        die Signatur nicht, ist auch die plan-abgeleitete Einkaufsliste gleich.
        """
        rows = self.db.execute(
            select(
                MealSlot.date,
                MealSlot.slot_type,
                MealSlot.planned_recipe_id,
                MealSlot.status,
            ).where(
                MealSlot.date >= start_date,
                MealSlot.date < start_date + timedelta(days=days),
            )
        ).all()
        return tuple(sorted((str(r[0]), r[1], r[2], r[3]) for r in rows))

    def _plan_day_with_reservations(
        self,
        target_date: date,
        reservations: dict[tuple[int, str], float],
        phase: GoalPhase | None,
    ) -> None:
        """Plan a single day using shared cross-day reservations."""
        slots = self._get_local_slots(target_date)
        engine = MealDecisionEngine(
            self.db, self.lager,
            ingredient_reservations=reservations,
            excluded_ingredient_ids=self._excluded_ids,
            user_allergens=self._user_allergens,
        )

        targets = self.profile_svc.derive_daily_targets()
        plannable = [s for s in slots if s.status != "eaten"]
        day_context = DayNutritionContext(
            targets=targets,
            slot_count_total=len(plannable) or 1,
            slot_index=0,
        )

        # Pre-fill context from eaten/pinned slots
        for slot in slots:
            if slot.status == "eaten" or slot.pinned:
                if slot.planned_recipe_id:
                    recipe = self.db.get(Recipe, slot.planned_recipe_id)
                    if recipe and recipe.nutrition_per_portion:
                        day_context.add_planned(recipe.nutrition_per_portion)

        used_recipe_ids: set[int] = set()
        for slot in slots:
            if (slot.pinned or slot.status == "eaten") and slot.planned_recipe_id:
                used_recipe_ids.add(slot.planned_recipe_id)

        for slot in slots:
            if slot.status == "eaten" or slot.pinned:
                continue
            if slot.planned_recipe_id is not None:
                continue
            result = engine.decide_best_for_slot(
                slot, phase,
                exclude_recipe_ids=used_recipe_ids,
                day_context=day_context,
            )
            if result:
                slot.planned_recipe_id = result.selected_recipe_id
                used_recipe_ids.add(result.selected_recipe_id)
                recipe = self.db.get(Recipe, result.selected_recipe_id)
                if recipe:
                    if recipe.nutrition_per_portion:
                        day_context.add_planned(recipe.nutrition_per_portion)
                    engine.reserve_recipe(recipe)

        self.db.flush()

    def _maybe_add_snacks(
        self,
        target_date: date,
        reservations: dict[tuple[int, str], float],
        phase: GoalPhase | None,
    ) -> None:
        """Add auto-snack slots if daily nutrition has a significant deficit."""
        slots = self._get_local_slots(target_date)
        existing_snack_count = sum(1 for s in slots if s.slot_type == "snack")
        if existing_snack_count >= settings.MAX_SNACKS_PER_DAY:
            return

        targets = self.profile_svc.derive_daily_targets()
        day_nutrition = {"kcal": 0.0, "protein_g": 0.0}

        used_recipe_ids: set[int] = set()
        for s in slots:
            if s.planned_recipe_id:
                used_recipe_ids.add(s.planned_recipe_id)
                recipe = self.db.get(Recipe, s.planned_recipe_id)
                if recipe and recipe.nutrition_per_portion:
                    n = recipe.nutrition_per_portion
                    day_nutrition["kcal"] += n.get("kcal", 0)
                    day_nutrition["protein_g"] += n.get("protein_g", 0)

        threshold = settings.SNACK_DEFICIT_THRESHOLD
        kcal_deficit_pct = 1.0 - (day_nutrition["kcal"] / targets.kcal) if targets.kcal > 0 else 0
        protein_deficit_pct = 1.0 - (day_nutrition["protein_g"] / targets.protein_g) if targets.protein_g > 0 else 0

        if kcal_deficit_pct <= threshold and protein_deficit_pct <= threshold:
            return

        snacks_to_add = min(
            settings.MAX_SNACKS_PER_DAY - existing_snack_count,
            2,  # hard cap per pass
        )

        engine = MealDecisionEngine(
            self.db, self.lager,
            ingredient_reservations=reservations,
            excluded_ingredient_ids=self._excluded_ids,
            user_allergens=self._user_allergens,
        )
        day_context = DayNutritionContext(
            targets=targets,
            slot_count_total=len(slots) + snacks_to_add,
            slot_index=len(slots),
        )
        day_context.planned_so_far.kcal = day_nutrition["kcal"]
        day_context.planned_so_far.protein_g = day_nutrition["protein_g"]

        for _ in range(snacks_to_add):
            snack_slot = MealSlot(date=target_date, slot_type="snack", status="planned")
            self.db.add(snack_slot)
            self.db.flush()

            candidates = engine.score_all_for_slot(
                snack_slot, phase,
                day_context=day_context,
                include_infeasible=False,
                tag_filter="snack",
            )
            # Filter out already-used recipes
            candidates = [c for c in candidates if c["recipe"].id not in used_recipe_ids]

            if not candidates:
                # No suitable snack found, remove the empty slot
                self.db.delete(snack_slot)
                self.db.flush()
                break

            best = candidates[0]["recipe"]
            snack_slot.planned_recipe_id = best.id
            used_recipe_ids.add(best.id)
            engine.reserve_recipe(best)
            if best.nutrition_per_portion:
                day_context.add_planned(best.nutrition_per_portion)
                day_nutrition["kcal"] += best.nutrition_per_portion.get("kcal", 0)
                day_nutrition["protein_g"] += best.nutrition_per_portion.get("protein_g", 0)

            # Re-check deficit
            kcal_deficit_pct = 1.0 - (day_nutrition["kcal"] / targets.kcal) if targets.kcal > 0 else 0
            protein_deficit_pct = 1.0 - (day_nutrition["protein_g"] / targets.protein_g) if targets.protein_g > 0 else 0
            if kcal_deficit_pct <= threshold and protein_deficit_pct <= threshold:
                break

        self.db.flush()

    def _add_recipe_reservations(
        self,
        reservations: dict[tuple[int, str], float],
        recipe_id: int,
    ) -> None:
        """Add ingredient amounts from a recipe to the reservations dict."""
        ri_rows = list(
            self.db.execute(
                select(RecipeIngredient)
                .where(RecipeIngredient.recipe_id == recipe_id)
                .options(joinedload(RecipeIngredient.ingredient))
            ).scalars().all()
        )
        for ri in ri_rows:
            if ri.optional_bool:
                continue
            ing = ri.ingredient
            if not ing or not ing.lager_product_id:
                continue
            key = (ing.lager_product_id, ri.unit)
            reservations[key] = reservations.get(key, 0) + ri.amount

    def plan_week(self, start_date: date, profile_id: int = 1) -> list[dict]:
        """Plan an entire week (7 days) starting from start_date.

        Delegates to plan_range for cross-day ingredient reservations,
        then returns a summary of each day with planned meals.
        Skips days that already have all slots planned.
        """
        days = 7

        # Use plan_range for optimal cross-day planning
        self.plan_range(start_date, days)

        # Build summary
        slot_order = {
            "breakfast": 0, "packed_lunch": 1,
            "lunch": 2, "dinner": 3, "snack": 4,
        }
        slot_labels = {
            "breakfast": "Fruehstueck",
            "packed_lunch": "Mitnahme",
            "lunch": "Mittagessen",
            "dinner": "Abendessen",
            "snack": "Snack",
        }

        summary: list[dict] = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            slots = self._get_local_slots(d)
            slots.sort(key=lambda s: slot_order.get(s.slot_type, 99))

            day_meals: list[dict] = []
            for slot in slots:
                recipe_name = None
                recipe_id = None
                nutrition = None
                if slot.planned_recipe_id:
                    recipe = self.db.get(Recipe, slot.planned_recipe_id)
                    if recipe:
                        recipe_name = recipe.name
                        recipe_id = recipe.id
                        nutrition = recipe.nutrition_per_portion
                day_meals.append({
                    "slot_id": slot.id,
                    "slot_type": slot.slot_type,
                    "slot_label": slot_labels.get(slot.slot_type, slot.slot_type),
                    "recipe_id": recipe_id,
                    "recipe_name": recipe_name,
                    "nutrition": nutrition,
                    "status": slot.status,
                    "pinned": slot.pinned,
                })

            summary.append({
                "date": d,
                "meals": day_meals,
            })

        return summary

    def replan_day(self, target_date: date) -> PlanDayResult:
        """Reset non-eaten slots and re-plan from scratch.

        Removes pins, deletes non-eaten slots, re-creates them
        (kalender-aware slot count), and runs plan_day.
        """
        existing = self._get_local_slots(target_date)
        for slot in existing:
            if slot.status != "eaten":
                self.db.delete(slot)
        self.db.flush()

        return self.plan_day(target_date)

    def update_feasibility(self, target_date: date) -> None:
        """Update feasibility_status and missing_ingredients for all planned slots on a date."""
        slots = self._get_local_slots(target_date)
        for slot in slots:
            if not slot.planned_recipe_id or slot.status == "eaten":
                slot.feasibility_status = "unknown"
                slot.missing_ingredients_json = None
                continue
            recipe = self.db.get(Recipe, slot.planned_recipe_id)
            if not recipe:
                slot.feasibility_status = "unknown"
                slot.missing_ingredients_json = None
                continue
            missing = self.engine._get_missing_ingredients(recipe)
            if not missing:
                slot.feasibility_status = "feasible"
                slot.missing_ingredients = []
            else:
                # Check if partially feasible (some but not all ingredients missing)
                has_required = self.engine._has_required_ingredients(recipe)
                slot.feasibility_status = "feasible" if has_required else "infeasible"
                slot.missing_ingredients = missing
        self.db.commit()

    def refresh_all_feasibility(self) -> int:
        """Re-check feasibility for all dates with planned (non-eaten) slots.

        Called after stock changes (e.g. meal committed/consumed) to keep
        the persisted feasibility_status and missing_ingredients up to date
        across all planned days, not just the current day.

        Uses a fresh MealDecisionEngine (empty availability cache) so that
        Lager queries reflect the latest stock levels.

        Returns the number of dates refreshed.  Gracefully skips if Lager
        is unavailable (no-op rather than failure).
        """
        if not self.lager.available:
            return 0

        planned_dates = self.get_planned_dates()
        if not planned_dates:
            return 0

        # Use a fresh engine instance so the availability cache starts
        # empty and all Lager queries hit current stock.
        fresh_engine = MealDecisionEngine(
            self.db, self.lager,
            excluded_ingredient_ids=self._excluded_ids,
            user_allergens=self._user_allergens,
        )

        for target_date in planned_dates:
            slots = self._get_local_slots(target_date)
            for slot in slots:
                if not slot.planned_recipe_id or slot.status == "eaten":
                    slot.feasibility_status = "unknown"
                    slot.missing_ingredients_json = None
                    continue
                recipe = self.db.get(Recipe, slot.planned_recipe_id)
                if not recipe:
                    slot.feasibility_status = "unknown"
                    slot.missing_ingredients_json = None
                    continue
                missing = fresh_engine._get_missing_ingredients(recipe)
                if not missing:
                    slot.feasibility_status = "feasible"
                    slot.missing_ingredients = []
                else:
                    has_required = fresh_engine._has_required_ingredients(recipe)
                    slot.feasibility_status = "feasible" if has_required else "infeasible"
                    slot.missing_ingredients = missing

        self.db.commit()
        return len(planned_dates)

    def get_planned_dates(self) -> list[date]:
        """Return dates that have planned (non-eaten) slots with recipes."""
        rows = self.db.execute(
            select(MealSlot.date)
            .where(
                MealSlot.planned_recipe_id.isnot(None),
                MealSlot.status != "eaten",
            )
            .distinct()
            .order_by(MealSlot.date)
        ).scalars().all()
        return list(rows)

    # ----- helpers -----

    def _get_local_slots(self, target_date: date) -> list[MealSlot]:
        return list(
            self.db.execute(
                select(MealSlot).where(MealSlot.date == target_date)
            ).scalars().all()
        )

    def _ensure_default_slots(self, target_date: date) -> list[MealSlot]:
        existing = self._get_local_slots(target_date)
        existing_types = {s.slot_type for s in existing}

        # Determine which slot types this day needs
        defaults = ["breakfast", "lunch", "dinner"]
        if self.kalender.needs_packed_lunch(target_date):
            defaults = ["breakfast", "packed_lunch", "lunch", "dinner"]

        # Add missing slot types
        new_slots = []
        for st in defaults:
            if st not in existing_types:
                s = MealSlot(date=target_date, slot_type=st, status="planned")
                self.db.add(s)
                self.db.flush()
                new_slots.append(s)

        # Remove packed_lunch if no longer needed and slot is untouched
        if "packed_lunch" not in defaults and "packed_lunch" in existing_types:
            for s in existing:
                if (
                    s.slot_type == "packed_lunch"
                    and s.status != "eaten"
                    and not s.pinned
                ):
                    self.db.delete(s)
                    existing = [x for x in existing if x.id != s.id]

        if new_slots:
            self.db.commit()

        # Return all slots for this date, ordered by a defined slot order
        all_slots = self._get_local_slots(target_date)
        slot_order = {"breakfast": 0, "packed_lunch": 1, "lunch": 2, "dinner": 3, "snack": 4}
        all_slots.sort(key=lambda s: slot_order.get(s.slot_type, 99))
        return all_slots

    @staticmethod
    def _slot_to_out(slot: MealSlot) -> MealSlotOut:
        recipe_name = None
        if slot.planned_recipe and slot.planned_recipe_id:
            recipe_name = slot.planned_recipe.name
        return MealSlotOut(
            id=slot.id,
            date=slot.date,
            slot_type=slot.slot_type,
            status=slot.status,
            planned_recipe_id=slot.planned_recipe_id,
            planned_recipe_name=recipe_name,
        )
