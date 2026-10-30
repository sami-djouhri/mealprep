"""Recipe service: listing, search, filtering, update, delete."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Ingredient, MealSlot, Recipe, RecipeHidden, RecipeIngredient
from app.schemas import RecipeUpdate


class RecipesService:
    def __init__(self, db: Session):
        self.db = db

    def hidden_recipe_ids(self) -> set[int]:
        """IDs der vom aktuellen Nutzer ausgeblendeten Rezepte (tenant-gescoped)."""
        return {
            rid
            for (rid,) in self.db.execute(select(RecipeHidden.recipe_id)).all()
        }

    def hide(self, recipe_id: int) -> bool:
        """Rezept fuer den aktuellen Nutzer ausblenden (idempotent)."""
        if not self.get(recipe_id):
            return False
        if recipe_id not in self.hidden_recipe_ids():
            self.db.add(RecipeHidden(recipe_id=recipe_id))
            self.db.flush()
        return True

    def unhide(self, recipe_id: int) -> bool:
        """Ausblendung aufheben (idempotent; True auch wenn nichts zu tun war)."""
        if not self.get(recipe_id):
            return False
        entry = self.db.execute(
            select(RecipeHidden).where(RecipeHidden.recipe_id == recipe_id)
        ).scalar_one_or_none()
        if entry is not None:
            self.db.delete(entry)
            self.db.flush()
        return True

    def list_all(
        self,
        excluded_ingredient_ids: list[int] | None = None,
        include_hidden: bool = False,
    ) -> list[Recipe]:
        recipes = list(
            self.db.execute(
                select(Recipe).options(joinedload(Recipe.ingredients))
            )
            .unique()
            .scalars()
            .all()
        )
        if not include_hidden:
            hidden = self.hidden_recipe_ids()
            if hidden:
                recipes = [r for r in recipes if r.id not in hidden]
        if excluded_ingredient_ids:
            recipes = self._filter_excluded(recipes, excluded_ingredient_ids)
        return recipes

    def get(self, recipe_id: int) -> Recipe | None:
        return (
            self.db.execute(
                select(Recipe)
                .options(joinedload(Recipe.ingredients))
                .where(Recipe.id == recipe_id)
            )
            .unique()
            .scalar_one_or_none()
        )

    def search(self, q: str) -> list[Recipe]:
        pattern = f"%{q}%"
        return (
            self.db.execute(
                select(Recipe)
                .options(joinedload(Recipe.ingredients))
                .where(Recipe.name.ilike(pattern))
            )
            .unique()
            .scalars()
            .all()
        )

    def filter(
        self,
        q: str = "",
        tags: list[str] | None = None,
        max_cook_time: int | None = None,
        max_kcal: float | None = None,
        excluded_ingredient_ids: list[int] | None = None,
        include_hidden: bool = False,
    ) -> list[Recipe]:
        stmt = select(Recipe).options(joinedload(Recipe.ingredients))
        if q:
            stmt = stmt.where(Recipe.name.ilike(f"%{q}%"))
        if max_cook_time:
            stmt = stmt.where(Recipe.cook_time_min <= max_cook_time)
        results = list(
            self.db.execute(stmt).unique().scalars().all()
        )
        if tags:
            results = [
                r for r in results if any(t in r.tags for t in tags)
            ]
        if max_kcal:
            results = [
                r
                for r in results
                if r.nutrition_per_portion
                and r.nutrition_per_portion.get("kcal", 0) <= max_kcal
            ]
        if not include_hidden:
            hidden = self.hidden_recipe_ids()
            if hidden:
                results = [r for r in results if r.id not in hidden]
        if excluded_ingredient_ids:
            results = self._filter_excluded(results, excluded_ingredient_ids)
        return results

    def update(self, recipe_id: int, data: RecipeUpdate) -> Recipe | None:
        recipe = self.get(recipe_id)
        if not recipe:
            return None

        if data.name is not None:
            recipe.name = data.name
        if data.portions_default is not None:
            recipe.portions_default = data.portions_default
        if data.cook_time_min is not None:
            recipe.cook_time_min = data.cook_time_min
        if data.tags is not None:
            recipe.tags = data.tags
        if data.nutrition_per_portion is not None:
            recipe.nutrition_per_portion = data.nutrition_per_portion.model_dump()
        if data.instructions is not None:
            recipe.instructions = data.instructions

        # Full replace of ingredients when provided
        if data.ingredients is not None:
            for ri in list(recipe.ingredients):
                self.db.delete(ri)
            self.db.flush()
            for ri_in in data.ingredients:
                if not self.db.get(Ingredient, ri_in.ingredient_id):
                    from app.domain import DomainError
                    raise DomainError(
                        f"Zutat {ri_in.ingredient_id} nicht gefunden",
                        {"ingredient_id": ri_in.ingredient_id},
                    )
                ri = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ri_in.ingredient_id,
                    amount=ri_in.amount,
                    unit=ri_in.unit,
                    optional_bool=ri_in.optional_bool,
                )
                ri.substitutes = ri_in.substitutes
                self.db.add(ri)

        self.db.flush()
        return self.get(recipe_id)

    def delete(self, recipe_id: int) -> bool:
        recipe = self.get(recipe_id)
        if not recipe:
            return False

        # Clean up recipe ingredients
        for ri in list(recipe.ingredients):
            self.db.delete(ri)

        # Eigene Ausblendungen des Rezepts mitraeumen (fremde sind tenant-gescoped
        # unsichtbar; verwaiste Eintraege sind harmlos, weil nur subtraktiv gefiltert wird).
        for hidden in self.db.execute(
            select(RecipeHidden).where(RecipeHidden.recipe_id == recipe_id)
        ).scalars().all():
            self.db.delete(hidden)
        # RecipeHidden hat keine relationship: ohne Flush ordnet die Unit-of-Work
        # das Recipe-DELETE evtl. vor das recipe_hidden-DELETE (FK-Fehler).
        self.db.flush()

        # Unlink meal slots referencing this recipe
        slots = list(
            self.db.execute(
                select(MealSlot).where(MealSlot.planned_recipe_id == recipe_id)
            ).scalars().all()
        )
        for slot in slots:
            slot.planned_recipe_id = None

        self.db.delete(recipe)
        self.db.flush()
        return True

    @staticmethod
    def _filter_excluded(
        recipes: list[Recipe], excluded_ids: list[int],
    ) -> list[Recipe]:
        excluded_set = set(excluded_ids)
        return [
            r for r in recipes
            if not any(
                ri.ingredient_id in excluded_set and not ri.optional_bool
                for ri in r.ingredients
            )
        ]
