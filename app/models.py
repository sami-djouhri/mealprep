import json
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db import Base

_OWNER = settings.DEFAULT_OWNER_SUB


def _owner_col() -> Mapped[str]:
    return mapped_column(String(128), nullable=False, index=True, server_default=_OWNER)


def _owner_col_nullable() -> Mapped[str | None]:
    return mapped_column(String(128), nullable=True, index=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class JSONEncodedList(String):
    """Stores a Python list as JSON text."""


class JSONEncodedDict(String):
    """Stores a Python dict as JSON text."""


def _json_default(val):
    if val is None:
        return None
    return json.dumps(val, ensure_ascii=False)


def _json_load(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    return json.loads(val)


# ---------------------------------------------------------------------------
# Ingredient
# ---------------------------------------------------------------------------

class Ingredient(Base):
    __tablename__ = "ingredient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_canonical: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    default_unit: Mapped[str] = mapped_column(String(20), default="g")

    # JSON text columns
    nutrition_per_100_json: Mapped[str | None] = mapped_column(Text)
    typical_pack_sizes_json: Mapped[str | None] = mapped_column(Text)
    shelf_life_type: Mapped[str] = mapped_column(String(20), default="MHD")
    synonyms_json: Mapped[str | None] = mapped_column(Text)

    # Allergen tags (comma-separated EU14: gluten, krebstiere, eier, fisch,
    # erdnuesse, soja, laktose, schalen, sellerie, senf, sesam, sulfite, lupine, weichtiere)
    allergens_json: Mapped[str | None] = mapped_column(Text)

    # Lager integration: maps this ingredient to a product in the Lager service
    lager_product_id: Mapped[int | None] = mapped_column(Integer)

    # convenience
    @property
    def allergens(self) -> list[str]:
        return _json_load(self.allergens_json) or []

    @allergens.setter
    def allergens(self, val: list[str]):
        self.allergens_json = _json_default(val)

    @property
    def nutrition_per_100(self) -> dict:
        return _json_load(self.nutrition_per_100_json) or {}

    @nutrition_per_100.setter
    def nutrition_per_100(self, val: dict):
        self.nutrition_per_100_json = _json_default(val)

    @property
    def typical_pack_sizes(self) -> list[int]:
        return _json_load(self.typical_pack_sizes_json) or []

    @typical_pack_sizes.setter
    def typical_pack_sizes(self, val: list[int]):
        self.typical_pack_sizes_json = _json_default(val)

    @property
    def synonyms(self) -> list[str]:
        return _json_load(self.synonyms_json) or []

    @synonyms.setter
    def synonyms(self, val: list[str]):
        self.synonyms_json = _json_default(val)


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------

class Recipe(Base):
    __tablename__ = "recipe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str | None] = _owner_col_nullable()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    portions_default: Mapped[int] = mapped_column(Integer, default=1)
    cook_time_min: Mapped[int] = mapped_column(Integer, default=15)

    tags_json: Mapped[str | None] = mapped_column(Text)
    nutrition_per_portion_json: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe")

    @property
    def tags(self) -> list[str]:
        return _json_load(self.tags_json) or []

    @tags.setter
    def tags(self, val: list[str]):
        self.tags_json = _json_default(val)

    @property
    def nutrition_per_portion(self) -> dict:
        return _json_load(self.nutrition_per_portion_json) or {}

    @nutrition_per_portion.setter
    def nutrition_per_portion(self, val: dict):
        self.nutrition_per_portion_json = _json_default(val)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str | None] = _owner_col_nullable()
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="g")
    optional_bool: Mapped[bool] = mapped_column(Boolean, default=False)
    substitutes_json: Mapped[str | None] = mapped_column(Text)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")
    ingredient: Mapped["Ingredient"] = relationship()

    @property
    def substitutes(self) -> list[int]:
        return _json_load(self.substitutes_json) or []

    @substitutes.setter
    def substitutes(self, val: list[int]):
        self.substitutes_json = _json_default(val)


# ---------------------------------------------------------------------------
# Goals & Body
# ---------------------------------------------------------------------------

class GoalPhase(Base):
    __tablename__ = "goal_phase"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    target_rate_pct_per_week: Mapped[float | None] = mapped_column(Float)
    macro_targets_json: Mapped[str | None] = mapped_column(Text)
    scoring_weights_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def macro_targets(self) -> dict:
        return _json_load(self.macro_targets_json) or {}

    @macro_targets.setter
    def macro_targets(self, val: dict):
        self.macro_targets_json = _json_default(val)

    @property
    def scoring_weights(self) -> dict:
        return _json_load(self.scoring_weights_json) or {
            "w_macro": 0.35, "w_mhd": 0.25, "w_eff": 0.15, "w_slot": 0.10, "w_variety": 0.15,
        }

    @scoring_weights.setter
    def scoring_weights(self, val: dict):
        self.scoring_weights_json = _json_default(val)


class BodyMetric(Base):
    __tablename__ = "body_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    date: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    waist_cm: Mapped[float | None] = mapped_column(Float)


# ---------------------------------------------------------------------------
# User Profile (Singleton, id=1)
# ---------------------------------------------------------------------------

class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    height_cm: Mapped[float] = mapped_column(Float, nullable=False, default=175.0)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False, default=75.0)
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(10), nullable=False, default="male")
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    activity_level: Mapped[str] = mapped_column(String(20), nullable=False, default="moderate")
    waist_cm: Mapped[float | None] = mapped_column(Float)
    allergies_json: Mapped[str | None] = mapped_column(Text)
    intolerances_json: Mapped[str | None] = mapped_column(Text)
    target_weight_kg: Mapped[float | None] = mapped_column(Float)
    kcal_target_override: Mapped[int | None] = mapped_column(Integer)
    excluded_ingredient_ids_json: Mapped[str | None] = mapped_column(Text)

    @property
    def allergies(self) -> list[str]:
        return _json_load(self.allergies_json) or []

    @allergies.setter
    def allergies(self, val: list[str]):
        self.allergies_json = _json_default(val)

    @property
    def intolerances(self) -> list[str]:
        return _json_load(self.intolerances_json) or []

    @intolerances.setter
    def intolerances(self, val: list[str]):
        self.intolerances_json = _json_default(val)

    @property
    def excluded_ingredient_ids(self) -> list[int]:
        return _json_load(self.excluded_ingredient_ids_json) or []

    @excluded_ingredient_ids.setter
    def excluded_ingredient_ids(self, val: list[int]):
        self.excluded_ingredient_ids_json = _json_default(val)


# ---------------------------------------------------------------------------
# Meal Slots
# ---------------------------------------------------------------------------

class MealSlot(Base):
    __tablename__ = "meal_slot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False)
    time_window_start: Mapped[str | None] = mapped_column(String(10))
    time_window_end: Mapped[str | None] = mapped_column(String(10))
    constraints_json: Mapped[str | None] = mapped_column(Text)
    planned_recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipe.id"))
    status: Mapped[str] = mapped_column(String(20), default="planned")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    feasibility_status: Mapped[str] = mapped_column(String(20), default="unknown")
    missing_ingredients_json: Mapped[str | None] = mapped_column(Text)

    planned_recipe: Mapped["Recipe | None"] = relationship()

    @property
    def constraints(self) -> dict:
        return _json_load(self.constraints_json) or {}

    @constraints.setter
    def constraints(self, val: dict):
        self.constraints_json = _json_default(val)

    @property
    def missing_ingredients(self) -> list:
        return _json_load(self.missing_ingredients_json) or []

    @missing_ingredients.setter
    def missing_ingredients(self, val: list):
        self.missing_ingredients_json = _json_default(val)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

class IntakeItem(Base):
    __tablename__ = "intake_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    source_type: Mapped[str] = mapped_column(String(30), default="FOOD")
    source_id: Mapped[int | None] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="g")
    nutrients_json: Mapped[str | None] = mapped_column(Text)
    meal_slot_id: Mapped[int | None] = mapped_column(ForeignKey("meal_slot.id"))
    tags_json: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(200))

    @property
    def nutrients(self) -> dict:
        return _json_load(self.nutrients_json) or {}

    @nutrients.setter
    def nutrients(self, val: dict):
        self.nutrients_json = _json_default(val)

    @property
    def tags(self) -> list[str]:
        return _json_load(self.tags_json) or []

    @tags.setter
    def tags(self, val: list[str]):
        self.tags_json = _json_default(val)


# ---------------------------------------------------------------------------
# Shopping
# ---------------------------------------------------------------------------

class ShoppingRule(Base):
    __tablename__ = "shopping_rule"
    __table_args__ = (
        UniqueConstraint("owner_sub", "ingredient_id", name="uq_shopping_rule_owner_ingredient"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"))
    min_stock: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="g")
    target_stock: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")

    ingredient: Mapped["Ingredient"] = relationship()


class ShoppingList(Base):
    __tablename__ = "shopping_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="open")

    lines: Mapped[list["ShoppingListLine"]] = relationship(back_populates="shopping_list")


class ShoppingListLine(Base):
    __tablename__ = "shopping_list_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    shopping_list_id: Mapped[int] = mapped_column(ForeignKey("shopping_list.id"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), nullable=False)
    needed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="g")
    suggested_packs_json: Mapped[str | None] = mapped_column(Text)
    reason_codes_json: Mapped[str | None] = mapped_column(Text)

    # Abhaken (0012). NULL = offen. ``lager_stock_entry_id`` merkt sich den im
    # Lager erzeugten Eintrag, damit die Ruecknahme genau ihn trifft und nicht
    # einen gleich aussehenden.
    gekauft_am: Mapped[datetime | None] = mapped_column(DateTime)
    gekaufte_menge: Mapped[float | None] = mapped_column(Float)
    lager_stock_entry_id: Mapped[int | None] = mapped_column(Integer)

    # Der ROHE Bedarf (0013), ohne Abzug des Bestands. ``needed_amount`` ist
    # der Bedarf minus Bestand ZUM ZEITPUNKT DER ERZEUGUNG; wer den beim
    # Anzeigen noch einmal gegen den heutigen Bestand haelt, zieht denselben
    # Vorrat zweimal ab. NULL heisst ausdruecklich "nicht nachrechnen" und
    # gilt fuer Zeilen aus lagers eigener Vorschlagsrechnung.
    bedarf_brutto: Mapped[float | None] = mapped_column(Float)

    shopping_list: Mapped["ShoppingList"] = relationship(back_populates="lines")
    ingredient: Mapped["Ingredient"] = relationship()

    @property
    def suggested_packs(self) -> list:
        return _json_load(self.suggested_packs_json) or []

    @suggested_packs.setter
    def suggested_packs(self, val: list):
        self.suggested_packs_json = _json_default(val)

    @property
    def reason_codes(self) -> list[str]:
        return _json_load(self.reason_codes_json) or []

    @reason_codes.setter
    def reason_codes(self, val: list[str]):
        self.reason_codes_json = _json_default(val)


# ---------------------------------------------------------------------------
# Supplements
# ---------------------------------------------------------------------------

class Supplement(Base):
    __tablename__ = "supplement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    dose: Mapped[str] = mapped_column(String(50), nullable=False)
    timing: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(20), default="daily")
    condition_tag: Mapped[str | None] = mapped_column(String(50))
    nutrition_json: Mapped[str | None] = mapped_column(Text)

    @property
    def nutrition(self) -> dict:
        return _json_load(self.nutrition_json) or {}

    @nutrition.setter
    def nutrition(self, val: dict):
        self.nutrition_json = _json_default(val)


class SupplementLog(Base):
    __tablename__ = "supplement_log"
    __table_args__ = (
        UniqueConstraint("supplement_id", "date", name="uq_supplement_log_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_sub: Mapped[str] = _owner_col()
    supplement_id: Mapped[int] = mapped_column(ForeignKey("supplement.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    taken: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# RecipeHidden: per-Nutzer ausgeblendete (globale) Rezepte ("nicht vorschlagen")
# ---------------------------------------------------------------------------

class RecipeHidden(Base):
    __tablename__ = "recipe_hidden"

    # Composite-PK: ein Ausblende-Eintrag pro (Nutzer, Rezept). owner_sub wird
    # vom Tenant-Scoping gestempelt (STRICT_MODELS in app/tenant.py).
    owner_sub: Mapped[str] = mapped_column(String(128), primary_key=True, server_default=_OWNER)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id"), primary_key=True)
