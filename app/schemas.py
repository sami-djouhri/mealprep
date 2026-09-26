from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------

class NutritionInfo(BaseModel):
    kcal: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    # Mikros (optional, schrittweise befuellt)
    iron_mg: float = 0
    zinc_mg: float = 0
    magnesium_mg: float = 0
    vitamin_c_mg: float = 0
    vitamin_d_iu: float = 0
    omega3_g: float = 0
    calcium_mg: float = 0


# ---------------------------------------------------------------------------
# Ingredient
# ---------------------------------------------------------------------------

class IngredientCreate(BaseModel):
    name_canonical: str = Field(..., max_length=200)
    category: str | None = Field(None, max_length=100)
    default_unit: str = Field("g", max_length=20)
    nutrition_per_100: NutritionInfo | None = None
    typical_pack_sizes: list[int] = Field(default_factory=list)
    shelf_life_type: str = "MHD"
    synonyms: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    lager_product_id: int | None = None


class IngredientOut(BaseModel):
    id: int
    name_canonical: str
    category: str | None
    default_unit: str
    nutrition_per_100: NutritionInfo | None = None
    typical_pack_sizes: list[int] = Field(default_factory=list)
    shelf_life_type: str
    allergens: list[str] = Field(default_factory=list)
    lager_product_id: int | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------

class RecipeIngredientCreate(BaseModel):
    ingredient_id: int
    amount: float
    unit: str = "g"
    optional_bool: bool = False
    substitutes: list[int] = Field(default_factory=list)


class RecipeCreate(BaseModel):
    name: str = Field(..., max_length=200)
    portions_default: int = 1
    cook_time_min: int = 15
    tags: list[str] = Field(default_factory=list)
    nutrition_per_portion: NutritionInfo | None = None
    ingredients: list[RecipeIngredientCreate] = Field(default_factory=list)
    instructions: str | None = None


class RecipeUpdate(BaseModel):
    name: str | None = None
    portions_default: int | None = None
    cook_time_min: int | None = None
    tags: list[str] | None = None
    nutrition_per_portion: NutritionInfo | None = None
    ingredients: list[RecipeIngredientCreate] | None = None
    instructions: str | None = None


class RecipeIngredientOut(BaseModel):
    id: int
    ingredient_id: int
    ingredient_name: str = ""
    amount: float
    unit: str
    optional_bool: bool

    model_config = {"from_attributes": True}


class RecipeOut(BaseModel):
    id: int
    name: str
    portions_default: int
    cook_time_min: int
    tags: list[str] = Field(default_factory=list)
    nutrition_per_portion: NutritionInfo | None = None
    ingredients: list[RecipeIngredientOut] = Field(default_factory=list)
    ingredient_categories: list[str] = Field(default_factory=list)
    instructions: str | None = None
    # Nur bei include_hidden=1 gesetzt: Rezept ist vom Nutzer ausgeblendet.
    hidden: bool = False

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

class ScoreBreakdown(BaseModel):
    macro_fit: float = 0
    expiry_util: float = 0
    effort: float = 0
    slot_compat: float = 0
    variety: float = 0
    total: float = 0


# ---------------------------------------------------------------------------
# Daily Macro Targets & Day Nutrition Context
# ---------------------------------------------------------------------------

class DailyMacroTargets(BaseModel):
    kcal: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0


class DayNutritionContext(BaseModel):
    targets: DailyMacroTargets
    planned_so_far: NutritionInfo = Field(default_factory=NutritionInfo)
    slot_count_total: int = 3
    slot_index: int = 0

    @property
    def remaining(self) -> NutritionInfo:
        return NutritionInfo(
            kcal=max(0, self.targets.kcal - self.planned_so_far.kcal),
            protein_g=max(0, self.targets.protein_g - self.planned_so_far.protein_g),
            carbs_g=max(0, self.targets.carbs_g - self.planned_so_far.carbs_g),
            fat_g=max(0, self.targets.fat_g - self.planned_so_far.fat_g),
            fiber_g=max(0, self.targets.fiber_g - self.planned_so_far.fiber_g),
        )

    @property
    def slots_left(self) -> int:
        return max(1, self.slot_count_total - self.slot_index)

    def add_planned(self, nutrition: dict) -> None:
        self.planned_so_far.kcal += nutrition.get("kcal", 0)
        self.planned_so_far.protein_g += nutrition.get("protein_g", 0)
        self.planned_so_far.carbs_g += nutrition.get("carbs_g", 0)
        self.planned_so_far.fat_g += nutrition.get("fat_g", 0)
        self.planned_so_far.fiber_g += nutrition.get("fiber_g", 0)
        self.slot_index += 1


class DecisionResult(BaseModel):
    selected_recipe_id: int
    selected_recipe_name: str = ""
    alternatives: list[int] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list, max_length=3)
    score_breakdown: dict[str, ScoreBreakdown] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Meal Slot
# ---------------------------------------------------------------------------

class MealSlotCreate(BaseModel):
    date: date
    slot_type: str
    time_window_start: str | None = None
    time_window_end: str | None = None
    planned_recipe_id: int | None = None


class MealSlotUpdate(BaseModel):
    slot_type: str | None = None
    time_window_start: str | None = None
    time_window_end: str | None = None
    planned_recipe_id: int | None = None
    status: str | None = None


class MealSlotOut(BaseModel):
    id: int
    date: date
    slot_type: str
    status: str
    planned_recipe_id: int | None
    planned_recipe_name: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Shopping
# ---------------------------------------------------------------------------

class ShoppingLineOut(BaseModel):
    id: int | None = None
    ingredient_id: int
    ingredient_name: str = ""
    #: Die gespeicherte Absicht: Bedarf minus Bestand zum Zeitpunkt der
    #: Erzeugung der Liste.
    needed_amount: float
    #: Der rohe Bedarf ohne Bestandsabzug. ``None`` heisst "nicht
    #: nachrechnen": die Zahl stammt aus lagers eigener Vorschlagsrechnung.
    bedarf_brutto: float | None = None
    #: Gegen den AKTUELLEN Bestand nachgerechnet, genau einmal und vom rohen
    #: Bedarf aus. Weicht von ``needed_amount`` ab, sobald jemand von Hand in
    #: lager ein- oder ausbucht.
    noch_noetig: float | None = None
    unit: str
    suggested_packs: list = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    strategic_info: StrategicInfo | None = None
    gekauft_am: datetime | None = None
    gekaufte_menge: float | None = None
    #: False heisst: diese Zeile kann nicht in den Bestand gebucht werden,
    #: weil die Zutat keinem Lager-Produkt zugeordnet ist.
    verknuepft: bool = True
    #: True heisst: lager war nicht erreichbar. ``noch_noetig`` ist dann die
    #: Absicht und keine Messung. Nicht mit "nichts da" verwechseln.
    bestand_unbekannt: bool = False

    model_config = {"from_attributes": True}


class ShoppingListOut(BaseModel):
    id: int
    created_at: datetime
    status: str
    lines: list[ShoppingLineOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EinkaufAbhaken(BaseModel):
    """Was beim Abhaken tatsaechlich gekauft wurde.

    Ohne Angabe gilt die geplante Menge. In der Praxis kauft man Packungen
    und keine Gramm, deshalb ist die Abweichung der Normalfall.
    """

    menge: float | None = Field(default=None, gt=0, le=1_000_000)
    mhd: date | None = None
    ort: str | None = Field(default=None, max_length=50)


class EinkaufAbhakenAntwort(BaseModel):
    line_id: int
    ingredient_name: str = ""
    gekaufte_menge: float | None = None
    unit: str = ""
    gekauft_am: datetime | None = None
    lager_stock_entry_id: int | None = None


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class PlanDayResult(BaseModel):
    date: date
    decisions: list[DecisionResult] = Field(default_factory=list)
    slots: list[MealSlotOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class UserProfileUpdate(BaseModel):
    height_cm: float | None = Field(None, ge=50, le=250)
    weight_kg: float | None = Field(None, ge=20, le=500)
    birth_date: date | None = None
    sex: str | None = None
    body_fat_pct: float | None = Field(None, ge=1, le=60)
    activity_level: str | None = None
    waist_cm: float | None = Field(None, ge=30, le=300)
    allergies: list[str] | None = None
    intolerances: list[str] | None = None
    target_weight_kg: float | None = None
    kcal_target_override: int | None = Field(None, ge=800, le=10000)
    excluded_ingredient_ids: list[int] | None = None


class UserProfileOut(BaseModel):
    id: int
    height_cm: float
    weight_kg: float
    birth_date: date | None
    sex: str
    body_fat_pct: float | None
    activity_level: str
    waist_cm: float | None
    allergies: list[str] = Field(default_factory=list)
    intolerances: list[str] = Field(default_factory=list)
    target_weight_kg: float | None
    kcal_target_override: int | None
    excluded_ingredient_ids: list[int] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TDEEOut(BaseModel):
    bmr: float
    tdee: float
    activity_level: str
    multiplier: float


class BodyMetricCreate(BaseModel):
    weight_kg: float
    metric_date: date | None = None
    body_fat_pct: float | None = None
    waist_cm: float | None = None


class BodyMetricOut(BaseModel):
    id: int
    date: date
    weight_kg: float
    body_fat_pct: float | None
    waist_cm: float | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Lager linking
# ---------------------------------------------------------------------------

class LinkLagerRequest(BaseModel):
    lager_product_id: int


class LagerAbgleichVorschlag(BaseModel):
    """Ein Zuordnungsvorschlag zwischen Zutat und Lager-Produkt.

    Vorschlag, keine Entscheidung: eine falsche Verknuepfung rechnet einen
    Vorrat gegen, den es nicht gibt, und streicht Dinge von der
    Einkaufsliste.
    """

    ingredient_id: int
    ingredient_name: str
    ingredient_unit: str
    lager_product_id: int
    lager_product_name: str
    lager_unit: str | None = None
    treffer_art: str
    einheit_gleich: bool
    hinweis: str | None = None


class LagerAbgleichAntwort(BaseModel):
    vorschlaege: list[LagerAbgleichVorschlag] = Field(default_factory=list)
    unverknuepft_gesamt: int = 0
    #: False heisst: Lager nicht erreichbar oder nicht eingerichtet. Dann ist
    #: eine leere Vorschlagsliste keine Aussage ueber die Zutaten.
    lager_erreichbar: bool = True


class LagerAbgleichPaar(BaseModel):
    ingredient_id: int
    lager_product_id: int


class LagerAbgleichUebernahme(BaseModel):
    paare: list[LagerAbgleichPaar] = Field(default_factory=list)


class FeasibilityItem(BaseModel):
    ingredient_id: int
    ingredient_name: str
    lager_product_id: int | None
    needed: float
    unit: str
    available: float
    sufficient: bool


class FeasibilityResult(BaseModel):
    recipe_id: int
    recipe_name: str
    feasible: bool
    items: list[FeasibilityItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Day Status & Goal Contribution
# ---------------------------------------------------------------------------

class GoalContribution(BaseModel):
    protein_label: str = ""     # "+35g P"
    carb_status: str = "ok"     # "ok" | "hoch" | "niedrig"
    fat_status: str = "ok"      # "ok" | "am Limit"


class NextMealSuggestion(BaseModel):
    slot_id: int
    slot_label: str
    recipe_name: str
    reason: str                 # "Deckt 35g Protein und nutzt ablaufendes Haechnchen"
    goal_contribution: GoalContribution


class DayStatus(BaseModel):
    status: str                 # "on_track" | "attention" | "at_risk"
    status_label: str           # "Auf Kurs" | "Anpassung noetig" | "Ziel gefaehrdet"
    remaining_kcal: float
    remaining_protein_g: float
    message: str
    next_meal: NextMealSuggestion | None = None


class NutrientDeficit(BaseModel):
    nutrient_label: str         # "Omega-3"
    deficit_pct: float          # 0.75 = 75% fehlt
    food_solution: str | None   # "Lachs oder Makrele einplanen"
    supplement_solution: str | None  # "Omega-3 Supplement nehmen"


class GoalMatchInfo(BaseModel):
    goal_match_pct: int = 0
    macro_balance: str = ""     # "P:gut K:gut F:hoch"
    prep_score_pct: int = 0
    feasible: bool = True


class StrategicInfo(BaseModel):
    impact_days: float = 0
    impact_meals: int = 0
    primary_nutrient: str = ""
    efficiency_hint: str = ""


# ---------------------------------------------------------------------------
# SPA Dashboard
# ---------------------------------------------------------------------------

class MissingIngredient(BaseModel):
    name: str
    needed: float
    available: float
    unit: str


class SlotRecipeInfo(BaseModel):
    id: int
    name: str
    cook_time_min: int = 0
    nutrition: NutritionInfo | None = None
    tags: list[str] = Field(default_factory=list)
    instructions: str | None = None


class DashboardSlot(BaseModel):
    id: int
    slot_type: str
    slot_label: str
    status: str
    recipe: SlotRecipeInfo | None = None
    pinned: bool = False
    feasibility_status: str = "unknown"
    missing_ingredients: list[MissingIngredient] = Field(default_factory=list)
    goal_contribution: GoalContribution | None = None
    slot_status: str = "planned"  # "optimal" | "planned" | "replace_recommended"


class ShoppingLine(BaseModel):
    ingredient: str
    amount: float
    unit: str
    reasons: list[str] = Field(default_factory=list)


class ShoppingInfo(BaseModel):
    lines: list[ShoppingLine] = Field(default_factory=list)


class DayPlan(BaseModel):
    date: date
    day_type: str = "frei"
    slots: list[DashboardSlot] = Field(default_factory=list)


class SupplementOut(BaseModel):
    id: int
    name: str
    dose: str
    timing: str
    taken_today: bool = False
    category: str = "daily"
    condition_tag: str | None = None
    hint: str | None = None
    nutrition: NutritionInfo | None = None


class IntakeLogRequest(BaseModel):
    recipe_id: int | None = None
    label: str | None = None
    nutrition: NutritionInfo | None = None
    amount: float = 1
    unit: str = "portion"


class IntakeLogOut(BaseModel):
    id: int
    label: str | None
    nutrition: NutritionInfo | None
    timestamp: datetime
    source_type: str


class DayStats(BaseModel):
    date: date
    kcal: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0


class StatsResponse(BaseModel):
    days: list[DayStats] = Field(default_factory=list)
    avg_kcal: float = 0
    avg_protein_g: float = 0
    period_days: int = 7


class Tagesziel(BaseModel):
    """Begruendung des Tagesziels.

    Steht bewusst in der Antwort und nicht nur im Protokoll: wenn nicht
    zwischen Trainings- und Ruhetag unterschieden wird, ist der Grund die
    eigentliche Auskunft ("erst 0 von 4 Trainings erfasst"), nicht ein
    Nebenumstand.
    """

    datum: str = ""
    verschoben: bool = False
    trainingstag: bool | None = None
    quelle: str | None = None
    anteil: float = 0.0
    trainings_pro_woche: float | None = None
    faktor: float | None = None
    basis_kcal: float | None = None
    grund: str = ""


class DashboardState(BaseModel):
    date: date
    slots: list[DashboardSlot] = Field(default_factory=list)
    targets: NutritionInfo = Field(default_factory=NutritionInfo)
    intake_totals: NutritionInfo = Field(default_factory=NutritionInfo)
    planned_totals: NutritionInfo = Field(default_factory=NutritionInfo)
    days_of_food: float = 0.0
    # ★ Ohne diese beiden Felder ist `days_of_food: 0.0` nicht lesbar: es
    # heisst dann "Vorrat leer" und "nicht gemessen" zugleich. Siehe
    # DaysOfFoodResult.
    days_of_food_belastbar: bool = False
    days_of_food_grund: str | None = None
    planned_dates: list[date] = Field(default_factory=list)
    days: list[DayPlan] = Field(default_factory=list)
    supplements: list[SupplementOut] = Field(default_factory=list)
    adhoc_intakes: list[IntakeLogOut] = Field(default_factory=list)
    supplement_hints: list[str] = Field(default_factory=list)
    day_status: DayStatus | None = None
    nutrient_deficits: list[NutrientDeficit] = Field(default_factory=list)
    #: Warum das Tagesziel so aussieht. ``verschoben: false`` plus ``grund``
    #: sagt, weshalb NICHT zwischen Trainings- und Ruhetag unterschieden
    #: wurde. Das ist die Auskunft, die sonst nur im Protokoll stuende.
    tagesziel: Tagesziel | None = None


# ---------------------------------------------------------------------------
# Swap Candidates
# ---------------------------------------------------------------------------

class SwapCandidateRecipe(BaseModel):
    id: int
    name: str
    cook_time_min: int = 0
    nutrition: NutritionInfo | None = None
    tags: list[str] = Field(default_factory=list)
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    feasible: bool = True
    missing_ingredients: list[MissingIngredient] = Field(default_factory=list)


class SwapCandidatesResponse(BaseModel):
    recipes: list[SwapCandidateRecipe] = Field(default_factory=list)
    slot_id: int
    show_infeasible: bool = True


# ---------------------------------------------------------------------------
# Days of Food
# ---------------------------------------------------------------------------

class DaysOfFoodResult(BaseModel):
    """Wie lange der Vorrat rechnerisch reicht, samt der Frage, ob das zaehlt.

    ★★ ``belastbar`` ist hier kein Beiwerk: ``days: 0.0`` bedeutete bis zum
    2026-09-13 dreierlei zugleich, naemlich "der Vorrat ist leer", "es ist
    nichts verknuepft" und "lager hat nicht geantwortet". Das Dashboard machte
    daraus einen roten Balken mit "~0.0 Tage", also eine Aussage ueber den
    Vorrat, wo gar keine Messung vorlag.

    Die Vorgabe ist bewusst ``False``: wer das Feld beim Bauen vergisst,
    bekommt "nicht belastbar" statt einer Zusicherung, die niemand geprueft
    hat. Und ohne ``grund`` geht es nicht durch, denn "unbekannt" ohne das
    Warum ist fuer den Leser dasselbe wie Schweigen.
    """

    days: float = 0.0
    limiting_ingredient: str | None = None
    details: list[dict] = Field(default_factory=list)
    belastbar: bool = False
    grund: str | None = None

    @model_validator(mode="after")
    def _grund_wenn_unbelastbar(self) -> "DaysOfFoodResult":
        if not self.belastbar and not self.grund:
            raise ValueError(
                "DaysOfFoodResult ohne belastbare Zahl braucht einen grund"
            )
        return self
