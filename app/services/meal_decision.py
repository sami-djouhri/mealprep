"""Deterministic meal-decision engine with explainability.

Uses LagerAdapter for ingredient availability and expiry checks.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import GoalPhase, MealSlot, Recipe, RecipeHidden, RecipeIngredient
from app.schemas import (
    DailyMacroTargets,
    DayNutritionContext,
    DecisionResult,
    GoalMatchInfo,
    NutritionInfo,
    ScoreBreakdown,
)
from app.services.lager_adapter import LagerAdapter

log = logging.getLogger(__name__)


class MealDecisionEngine:
    def __init__(
        self,
        db: Session,
        lager: LagerAdapter | None = None,
        ingredient_reservations: dict[tuple[int, str], float] | None = None,
        excluded_ingredient_ids: set[int] | None = None,
        user_allergens: set[str] | None = None,
    ):
        self.db = db
        self.lager = lager or LagerAdapter()
        # Availability cache: (product_id, unit) -> qty
        self._availability_cache: dict[tuple[int, str], float] = {}
        # Expiring product IDs (loaded once per decision round)
        self._expiring_product_ids: set[int] | None = None
        # Cross-day ingredient reservations from already-planned slots
        self._ingredient_reservations: dict[tuple[int, str], float] = (
            ingredient_reservations or {}
        )
        # Excluded ingredient IDs from user profile
        self._excluded_ingredient_ids: set[int] = excluded_ingredient_ids or set()
        # User allergens/intolerances (lowercase keys matching ingredient allergens)
        self._user_allergens: set[str] = user_allergens or set()

    def decide_best_for_slot(
        self,
        slot: MealSlot,
        phase: GoalPhase | None,
        exclude_recipe_ids: set[int] | None = None,
        day_context: DayNutritionContext | None = None,
    ) -> DecisionResult | None:
        recipes = self._load_candidates()
        if not recipes:
            return None

        max_cook = settings.DEFAULT_MAX_COOK_TIME_MIN
        slot_constraints = slot.constraints or {}
        if "max_cook_time" in slot_constraints:
            max_cook = slot_constraints["max_cook_time"]

        # 1) Filter: cook time
        candidates = [r for r in recipes if r.cook_time_min <= max_cook]
        if not candidates:
            candidates = recipes  # fallback: ignore cook time filter

        # 1b) Exclude already-selected recipes (dedup within a day)
        if exclude_recipe_ids:
            deduped = [r for r in candidates if r.id not in exclude_recipe_ids]
            if deduped:
                candidates = deduped

        # 2) Filter: must-have ingredients available (via Lager)
        feasible = []
        for r in candidates:
            if self._has_required_ingredients(r):
                feasible.append(r)
        if not feasible:
            feasible = candidates  # fallback: score everything

        # 3) Score
        weights = (phase.scoring_weights if phase else
                   {"w_macro": 0.35, "w_mhd": 0.25, "w_eff": 0.15, "w_slot": 0.10, "w_variety": 0.15})
        wm = weights.get("w_macro", 0.35)
        we = weights.get("w_mhd", 0.25)
        wf = weights.get("w_eff", 0.15)
        ws = weights.get("w_slot", 0.10)
        wv = weights.get("w_variety", 0.15)

        scored: list[tuple[Recipe, ScoreBreakdown]] = []
        for r in feasible:
            macro = self._macro_gap_score(r, day_context)
            expiry = self._expiry_utilization_score(r)
            effort = self._effort_score(r, max_cook)
            slot_c = 1.0  # MVP
            var = self._variety_score(r, day_context)
            total = wm * macro + we * expiry + wf * effort + ws * slot_c + wv * var
            bd = ScoreBreakdown(
                macro_fit=round(macro, 4),
                expiry_util=round(expiry, 4),
                effort=round(effort, 4),
                slot_compat=round(slot_c, 4),
                variety=round(var, 4),
                total=round(total, 4),
            )
            scored.append((r, bd))

        scored.sort(key=lambda x: x[1].total, reverse=True)

        best, best_bd = scored[0]
        alternatives = [r.id for r, _ in scored[1:3]]
        explanation = self._build_explanation(best, best_bd, weights, day_context)
        breakdown = {str(r.id): bd for r, bd in scored}

        return DecisionResult(
            selected_recipe_id=best.id,
            selected_recipe_name=best.name,
            alternatives=alternatives,
            explanation=explanation,
            score_breakdown=breakdown,
        )

    def reserve_recipe(self, recipe: Recipe) -> None:
        """Reserve ingredients of a recipe for later planning rounds."""
        for ri in recipe.ingredients:
            if ri.optional_bool:
                continue
            ing = ri.ingredient
            if not ing or not ing.lager_product_id:
                continue
            key = (ing.lager_product_id, ri.unit)
            self._ingredient_reservations[key] = (
                self._ingredient_reservations.get(key, 0) + ri.amount
            )
        # Invalidate cache for affected keys
        for key in list(self._availability_cache.keys()):
            if key in self._ingredient_reservations:
                del self._availability_cache[key]

    def score_all_for_slot(
        self,
        slot: MealSlot,
        phase: GoalPhase | None,
        day_context: DayNutritionContext | None = None,
        include_infeasible: bool = True,
        tag_filter: str | None = None,
    ) -> list[dict]:
        """Score all recipes for a slot and return full candidate list.

        Returns list of dicts with keys:
          recipe, score, feasible, missing_ingredients
        Sorted by total score descending, feasible first.
        """
        recipes = self._load_candidates()
        if tag_filter:
            recipes = [r for r in recipes if tag_filter in r.tags]
        if not recipes:
            return []

        weights = (phase.scoring_weights if phase else
                   {"w_macro": 0.35, "w_mhd": 0.25, "w_eff": 0.15, "w_slot": 0.10, "w_variety": 0.15})
        wm = weights.get("w_macro", 0.35)
        we = weights.get("w_mhd", 0.25)
        wf = weights.get("w_eff", 0.15)
        ws = weights.get("w_slot", 0.10)
        wv = weights.get("w_variety", 0.15)
        max_cook = settings.DEFAULT_MAX_COOK_TIME_MIN

        results = []
        for r in recipes:
            feasible = self._has_required_ingredients(r)
            missing = self._get_missing_ingredients(r) if not feasible else []

            macro = self._macro_gap_score(r, day_context)
            expiry = self._expiry_utilization_score(r)
            effort = self._effort_score(r, max_cook)
            slot_c = 1.0
            var = self._variety_score(r, day_context)
            total = wm * macro + we * expiry + wf * effort + ws * slot_c + wv * var
            bd = ScoreBreakdown(
                macro_fit=round(macro, 4),
                expiry_util=round(expiry, 4),
                effort=round(effort, 4),
                slot_compat=round(slot_c, 4),
                variety=round(var, 4),
                total=round(total, 4),
            )

            if not include_infeasible and not feasible:
                continue

            results.append({
                "recipe": r,
                "score": bd,
                "feasible": feasible,
                "missing_ingredients": missing,
            })

        # Sort: feasible first, then by total score descending
        results.sort(key=lambda x: (not x["feasible"], -x["score"].total))
        return results

    def compute_goal_match(
        self,
        recipe: Recipe,
        day_context: DayNutritionContext | None = None,
    ) -> GoalMatchInfo:
        """Compute how well a recipe matches the current day's goals."""
        # Macro fit score
        macro_score = self._macro_gap_score(recipe, day_context)
        goal_match_pct = int(round(macro_score * 100))

        # Macro balance label
        n = recipe.nutrition_per_portion or {}
        protein = n.get("protein_g", 0)
        carbs = n.get("carbs_g", 0)
        fat = n.get("fat_g", 0)

        def balance_label(val: float, name: str, low: float, high: float) -> str:
            if val < low:
                return f"{name}:niedrig"
            elif val > high:
                return f"{name}:hoch"
            return f"{name}:gut"

        # Rough heuristic thresholds for a single meal
        p_label = balance_label(protein, "P", 15, 60)
        k_label = balance_label(carbs, "K", 20, 80)
        f_label = balance_label(fat, "F", 5, 35)
        macro_balance = f"{p_label} {k_label} {f_label}"

        # Prep score: multi-portion + moderate cook time
        portions = recipe.portions_default or 1
        cook_time = recipe.cook_time_min or 0
        portion_score = min(portions / 4, 1.0)  # up to 4 portions = 1.0
        time_score = max(0, 1.0 - cook_time / 60) if cook_time > 0 else 0.5
        prep_score_pct = int(round((0.6 * portion_score + 0.4 * time_score) * 100))

        feasible = self._has_required_ingredients(recipe)

        return GoalMatchInfo(
            goal_match_pct=goal_match_pct,
            macro_balance=macro_balance,
            prep_score_pct=prep_score_pct,
            feasible=feasible,
        )

    def _get_missing_ingredients(self, recipe: Recipe) -> list[dict]:
        """Return list of missing ingredients with needed/available amounts."""
        missing = []
        for ri in recipe.ingredients:
            if ri.optional_bool:
                continue
            ing = ri.ingredient
            if not ing or not ing.lager_product_id:
                continue
            avail = self._get_available_cached(ing.lager_product_id, ri.unit)
            if avail < ri.amount - 0.001:
                missing.append({
                    "name": ing.name_canonical,
                    "needed": ri.amount,
                    "available": round(avail, 1),
                    "unit": ri.unit,
                })
        return missing

    # ----- scoring components -----

    def _macro_fit_score_legacy(self, recipe: Recipe) -> float:
        """Original isolated macro score (protein/kcal ratio). Used as fallback."""
        n = recipe.nutrition_per_portion
        if not n:
            return 0.0
        kcal = n.get("kcal", 1) or 1
        protein = n.get("protein_g", 0) or 0
        ratio = protein / kcal  # higher is better
        absolute_bonus = min(protein / 50.0, 1.0)  # up to 50g protein = 1.0
        return min((ratio * 30 + absolute_bonus) / 2.0, 1.0)

    def _macro_gap_score(
        self, recipe: Recipe, day_context: DayNutritionContext | None
    ) -> float:
        """Score how well this recipe fills the remaining daily macro gap."""
        if day_context is None:
            return self._macro_fit_score_legacy(recipe)

        n = recipe.nutrition_per_portion
        if not n:
            return 0.0

        remaining = day_context.remaining
        slots_left = day_context.slots_left

        # Ideal values for this slot = remaining / slots_left
        ideal_kcal = remaining.kcal / slots_left
        ideal_protein = remaining.protein_g / slots_left
        ideal_carbs = remaining.carbs_g / slots_left
        ideal_fat = remaining.fat_g / slots_left
        ideal_fiber = remaining.fiber_g / slots_left

        actual = {
            "kcal": n.get("kcal", 0),
            "protein_g": n.get("protein_g", 0),
            "carbs_g": n.get("carbs_g", 0),
            "fat_g": n.get("fat_g", 0),
            "fiber_g": n.get("fiber_g", 0),
        }

        def closeness(act: float, ideal: float) -> float:
            if ideal <= 0:
                return 1.0 if act <= 0 else 0.5
            return max(0.0, 1.0 - abs(act - ideal) / ideal)

        scores = {
            "protein": closeness(actual["protein_g"], ideal_protein),
            "kcal": closeness(actual["kcal"], ideal_kcal),
            "fat": closeness(actual["fat_g"], ideal_fat),
            "carbs": closeness(actual["carbs_g"], ideal_carbs),
            "fiber": closeness(actual["fiber_g"], ideal_fiber),
        }

        # Weighted average: Protein 35%, kcal 25%, Fat 15%, Carbs 15%, Fiber 10%
        return (
            0.35 * scores["protein"]
            + 0.25 * scores["kcal"]
            + 0.15 * scores["fat"]
            + 0.15 * scores["carbs"]
            + 0.10 * scores["fiber"]
        )

    def _variety_score(
        self, recipe: Recipe, day_context: DayNutritionContext | None
    ) -> float:
        """Score macro-profile diversity vs. what has been planned so far."""
        if day_context is None or day_context.slot_index == 0:
            return 0.5  # neutral for first slot or no context

        n = recipe.nutrition_per_portion
        if not n:
            return 0.5

        def macro_profile(kcal: float, protein: float, carbs: float, fat: float):
            """Return (pct_protein, pct_carbs, pct_fat) of kcal."""
            if kcal <= 0:
                return (0.33, 0.33, 0.33)
            return (
                (protein * 4) / kcal,
                (carbs * 4) / kcal,
                (fat * 9) / kcal,
            )

        # Profile of this recipe
        r_profile = macro_profile(
            n.get("kcal", 0),
            n.get("protein_g", 0),
            n.get("carbs_g", 0),
            n.get("fat_g", 0),
        )

        # Average profile of what's been planned so far
        sf = day_context.planned_so_far
        sf_kcal = sf.kcal or 1
        avg_profile = macro_profile(sf_kcal, sf.protein_g, sf.carbs_g, sf.fat_g)

        # Euclidean distance between profiles (max theoretical ~1.0)
        diff = sum((a - b) ** 2 for a, b in zip(r_profile, avg_profile)) ** 0.5
        # Normalize: max realistic distance ~1.0, cap at 1.0
        return min(diff / 0.8, 1.0)

    def _expiry_utilization_score(self, recipe: Recipe) -> float:
        """Score based on how many required ingredients use expiring stock (via Lager)."""
        if self._expiring_product_ids is None:
            self._load_expiring_product_ids()

        count_expiring = 0
        total_required = 0
        for ri in recipe.ingredients:
            if ri.optional_bool:
                continue
            total_required += 1
            ing = ri.ingredient
            if ing and ing.lager_product_id and ing.lager_product_id in self._expiring_product_ids:
                count_expiring += 1
        if total_required == 0:
            return 0.0
        return count_expiring / total_required

    def _effort_score(self, recipe: Recipe, max_cook: int) -> float:
        if max_cook <= 0:
            return 1.0
        return max(0.0, 1.0 - recipe.cook_time_min / max_cook)

    # ----- helpers -----

    def _has_required_ingredients(self, recipe: Recipe) -> bool:
        for ri in recipe.ingredients:
            if ri.optional_bool:
                continue
            ing = ri.ingredient
            if not ing or not ing.lager_product_id:
                continue  # unmapped ingredient: skip availability check
            avail = self._get_available_cached(ing.lager_product_id, ri.unit)
            if avail < ri.amount - 0.001:
                return False
        return True

    def _get_available_cached(self, product_id: int, unit: str) -> float:
        key = (product_id, unit)
        if key not in self._availability_cache:
            # ★ Der Zwischenspeicher hier fasst WIEDERHOLTE Fragen nach
            # demselben Produkt zusammen, nicht die Zahl der Produkte. Bei
            # vielen Rezepten sind das immer noch Dutzende Aufrufe, und lager
            # deckelt bei 60 je Minute. Ein einmal geladener Schnappschuss
            # beantwortet alle davon ohne einen weiteren Aufruf; ist keiner
            # geladen, geht `get_available` wie bisher ueber HTTP.
            self.lager.schnappschuss_laden()
            raw = self.lager.get_available(product_id, unit)
            reserved = self._ingredient_reservations.get(key, 0)
            self._availability_cache[key] = max(0, raw - reserved)
        return self._availability_cache[key]

    def _load_expiring_product_ids(self) -> None:
        entries = self.lager.get_expiring(days=settings.EXPIRY_THRESHOLD_DAYS)
        self._expiring_product_ids = {
            e.get("product_id") for e in entries if e.get("product_id")
        }

    def _load_candidates(self) -> list[Recipe]:
        recipes = list(
            self.db.execute(
                select(Recipe).options(
                    joinedload(Recipe.ingredients).joinedload(RecipeIngredient.ingredient)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        # Vom Nutzer ausgeblendete Rezepte ("nicht vorschlagen"): tenant-gescoped.
        hidden = {
            rid for (rid,) in self.db.execute(select(RecipeHidden.recipe_id)).all()
        }
        if hidden:
            recipes = [r for r in recipes if r.id not in hidden]
        if self._excluded_ingredient_ids:
            recipes = [
                r for r in recipes
                if not any(
                    ri.ingredient_id in self._excluded_ingredient_ids
                    and not ri.optional_bool
                    for ri in r.ingredients
                )
            ]
        if self._user_allergens:
            filtered = []
            for r in recipes:
                blocked = self._recipe_matches_allergens(r)
                if blocked:
                    log.info(
                        "Rezept '%s' (ID %d) wegen Allergenen ausgeschlossen: %s",
                        r.name, r.id, ", ".join(blocked),
                    )
                else:
                    filtered.append(r)
            recipes = filtered
        return recipes

    def _recipe_matches_allergens(self, recipe: Recipe) -> list[str]:
        """Return list of matched allergen labels if recipe contains any user allergens.

        Only checks non-optional ingredients. Returns empty list if safe.
        """
        matched: set[str] = set()
        for ri in recipe.ingredients:
            if ri.optional_bool:
                continue
            ing = ri.ingredient
            if not ing:
                continue
            ing_allergens = {a.lower() for a in ing.allergens}
            overlap = ing_allergens & self._user_allergens
            matched.update(overlap)
        return sorted(matched)

    def _build_explanation(
        self,
        recipe: Recipe,
        bd: ScoreBreakdown,
        weights: dict,
        day_context: DayNutritionContext | None = None,
    ) -> list[str]:
        reasons: list[tuple[float, str]] = []
        if bd.macro_fit > 0.3:
            if day_context is not None:
                rem = day_context.remaining
                reasons.append((
                    bd.macro_fit * weights.get("w_macro", 0.35),
                    f"Fuellt Tagesluecke gut (noch {rem.protein_g:.0f}g Protein, {rem.kcal:.0f} kcal offen)",
                ))
            else:
                reasons.append((
                    bd.macro_fit * weights.get("w_macro", 0.35),
                    f"Gutes Makroprofil (Protein/kcal-Verhaeltnis: {bd.macro_fit:.2f})",
                ))
        if bd.expiry_util > 0:
            reasons.append((
                bd.expiry_util * weights.get("w_mhd", 0.25),
                f"Nutzt bald ablaufende Zutaten ({bd.expiry_util:.0%} der Zutaten nahe MHD)",
            ))
        if bd.effort > 0.5:
            reasons.append((
                bd.effort * weights.get("w_eff", 0.15),
                f"Schnelle Zubereitung ({recipe.cook_time_min} min)",
            ))
        if bd.variety > 0.6 and weights.get("w_variety", 0.15) > 0:
            reasons.append((
                bd.variety * weights.get("w_variety", 0.15),
                "Bringt Abwechslung bei den Makros",
            ))
        reasons.append((
            bd.slot_compat * weights.get("w_slot", 0.10),
            "Passt zum Slot-Typ",
        ))
        reasons.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in reasons[:3]]
