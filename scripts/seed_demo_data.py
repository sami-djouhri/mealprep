"""Seed demo data: ingredients, recipes, user profile, goal phase, shopping rules."""

from datetime import date, timedelta

from app.db import SessionLocal, engine, Base
from app.models import (
    BodyMetric,
    GoalPhase,
    Ingredient,
    Recipe,
    RecipeIngredient,
    ShoppingRule,
    Supplement,
    UserProfile,
)

# Ensure tables exist
Base.metadata.create_all(bind=engine)


def seed():
    db = SessionLocal()
    try:
        # Skip if already seeded
        if db.query(Ingredient).first():
            print("Datenbank bereits befuellt, ueberspringe Seed.")
            return

        today = date.today()

        # ---------------------------------------------------------------
        # Ingredients (lager_product_id=None, manual mapping required)
        # ---------------------------------------------------------------
        ingredients = {}

        def add_ing(key, name, category, unit, shelf, nutrition, packs):
            ing = Ingredient(
                name_canonical=name, category=category,
                default_unit=unit, shelf_life_type=shelf,
            )
            ing.nutrition_per_100 = nutrition
            ing.typical_pack_sizes = packs
            ingredients[key] = ing
            db.add(ing)

        # --- Getreide & Beilagen ---
        add_ing("haferflocken", "Haferflocken", "Getreide", "g", "MHD",
                {"kcal": 372, "protein_g": 13.5, "carbs_g": 58.7, "fat_g": 7.0, "fiber_g": 10.0},
                [500, 1000])
        add_ing("reis", "Reis", "Getreide", "g", "MHD",
                {"kcal": 349, "protein_g": 6.8, "carbs_g": 78.0, "fat_g": 0.6, "fiber_g": 1.3},
                [500, 1000])
        add_ing("nudeln", "Nudeln", "Getreide", "g", "MHD",
                {"kcal": 353, "protein_g": 12.5, "carbs_g": 70.5, "fat_g": 1.5, "fiber_g": 3.0},
                [500])
        add_ing("vollkorntoast", "Vollkorntoast", "Getreide", "piece", "FRESH",
                {"kcal": 250, "protein_g": 9.0, "carbs_g": 42.0, "fat_g": 3.5, "fiber_g": 6.0},
                [1])
        add_ing("kartoffeln", "Kartoffeln", "Beilage", "g", "MHD",
                {"kcal": 77, "protein_g": 2.0, "carbs_g": 17.0, "fat_g": 0.1, "fiber_g": 2.2},
                [2000, 5000])
        add_ing("tortilla", "Tortilla-Wraps", "Getreide", "piece", "MHD",
                {"kcal": 310, "protein_g": 8.0, "carbs_g": 52.0, "fat_g": 8.0, "fiber_g": 2.0},
                [6, 8])

        # --- Protein ---
        add_ing("eier", "Eier", "Protein", "piece", "MHD",
                {"kcal": 155, "protein_g": 13.0, "carbs_g": 1.1, "fat_g": 11.0, "fiber_g": 0},
                [6, 10])
        add_ing("haehnchen", "Haehnchenbrust", "Protein", "g", "FRESH",
                {"kcal": 165, "protein_g": 31.0, "carbs_g": 0, "fat_g": 3.6, "fiber_g": 0},
                [400, 500])
        add_ing("putenbrust", "Putenbrust", "Protein", "g", "FRESH",
                {"kcal": 135, "protein_g": 30.0, "carbs_g": 0, "fat_g": 1.5, "fiber_g": 0},
                [400])
        add_ing("hackfleisch", "Hackfleisch (Rind)", "Protein", "g", "FRESH",
                {"kcal": 212, "protein_g": 26.0, "carbs_g": 0, "fat_g": 12.0, "fiber_g": 0},
                [400, 500])
        add_ing("lachs", "Lachsfilet", "Protein", "g", "FRESH",
                {"kcal": 208, "protein_g": 20.0, "carbs_g": 0, "fat_g": 13.0, "fiber_g": 0},
                [200, 400])
        add_ing("thunfisch", "Thunfisch (Dose)", "Protein", "g", "MHD",
                {"kcal": 116, "protein_g": 26.0, "carbs_g": 0, "fat_g": 1.0, "fiber_g": 0},
                [150])
        add_ing("speck", "Speck (gewuerfelt)", "Protein", "g", "FRESH",
                {"kcal": 300, "protein_g": 15.0, "carbs_g": 0, "fat_g": 27.0, "fiber_g": 0},
                [150, 200])

        # --- Milchprodukte ---
        add_ing("skyr", "Skyr", "Milchprodukt", "g", "FRESH",
                {"kcal": 63, "protein_g": 11.0, "carbs_g": 4.0, "fat_g": 0.2, "fiber_g": 0},
                [450])
        add_ing("magerquark", "Magerquark", "Milchprodukt", "g", "FRESH",
                {"kcal": 67, "protein_g": 12.0, "carbs_g": 4.0, "fat_g": 0.3, "fiber_g": 0},
                [250, 500])
        add_ing("milch", "Milch (1.5%)", "Milchprodukt", "ml", "FRESH",
                {"kcal": 47, "protein_g": 3.4, "carbs_g": 4.9, "fat_g": 1.5, "fiber_g": 0},
                [1000])
        add_ing("kaese", "Kaese (gerieben)", "Milchprodukt", "g", "FRESH",
                {"kcal": 365, "protein_g": 25.0, "carbs_g": 2.0, "fat_g": 28.0, "fiber_g": 0},
                [200, 400])
        add_ing("sahne", "Sahne", "Milchprodukt", "ml", "FRESH",
                {"kcal": 204, "protein_g": 2.4, "carbs_g": 3.2, "fat_g": 20.0, "fiber_g": 0},
                [200])
        add_ing("butter", "Butter", "Milchprodukt", "g", "FRESH",
                {"kcal": 741, "protein_g": 0.7, "carbs_g": 0.6, "fat_g": 83.0, "fiber_g": 0},
                [250])

        # --- Gemuese ---
        add_ing("tk_gemuese", "TK-Gemuese (Mix)", "Gemuese", "g", "MHD",
                {"kcal": 35, "protein_g": 2.5, "carbs_g": 4.0, "fat_g": 0.3, "fiber_g": 3.0},
                [450, 750])
        add_ing("brokkoli", "Brokkoli", "Gemuese", "g", "FRESH",
                {"kcal": 34, "protein_g": 2.8, "carbs_g": 4.0, "fat_g": 0.4, "fiber_g": 3.0},
                [500])
        add_ing("zwiebeln", "Zwiebeln", "Gemuese", "g", "MHD",
                {"kcal": 40, "protein_g": 1.1, "carbs_g": 9.3, "fat_g": 0.1, "fiber_g": 1.7},
                [1000])
        add_ing("paprika", "Paprika", "Gemuese", "piece", "FRESH",
                {"kcal": 31, "protein_g": 1.0, "carbs_g": 6.0, "fat_g": 0.3, "fiber_g": 1.7},
                [1])
        add_ing("blattspinat", "Blattspinat (TK)", "Gemuese", "g", "MHD",
                {"kcal": 23, "protein_g": 2.9, "carbs_g": 1.6, "fat_g": 0.4, "fiber_g": 2.2},
                [450])

        # --- Konserven ---
        add_ing("tomaten_dose", "Tomaten (Dose)", "Konserve", "g", "MHD",
                {"kcal": 26, "protein_g": 1.0, "carbs_g": 4.2, "fat_g": 0.1, "fiber_g": 1.0},
                [400])
        add_ing("kidneybohnen", "Kidneybohnen (Dose)", "Konserve", "g", "MHD",
                {"kcal": 105, "protein_g": 7.5, "carbs_g": 14.0, "fat_g": 0.5, "fiber_g": 6.0},
                [400])
        add_ing("linsen_dose", "Linsen (Dose)", "Konserve", "g", "MHD",
                {"kcal": 93, "protein_g": 7.6, "carbs_g": 12.0, "fat_g": 0.4, "fiber_g": 4.0},
                [400])
        add_ing("kokosmilch", "Kokosmilch", "Konserve", "ml", "MHD",
                {"kcal": 197, "protein_g": 2.0, "carbs_g": 3.0, "fat_g": 20.0, "fiber_g": 0},
                [400])

        # --- Fette & Sonstiges ---
        add_ing("olivenoel", "Olivenoel", "Fett", "ml", "NO_EXPIRY",
                {"kcal": 884, "protein_g": 0, "carbs_g": 0, "fat_g": 100, "fiber_g": 0},
                [500, 750])
        add_ing("erdnussbutter", "Erdnussbutter", "Fett", "g", "MHD",
                {"kcal": 588, "protein_g": 25.0, "carbs_g": 20.0, "fat_g": 50.0, "fiber_g": 6.0},
                [350])

        # --- Obst ---
        add_ing("banane", "Banane", "Obst", "piece", "FRESH",
                {"kcal": 89, "protein_g": 1.1, "carbs_g": 22.8, "fat_g": 0.3, "fiber_g": 2.6},
                [1])
        add_ing("tk_beeren", "TK-Beeren (Mix)", "Obst", "g", "MHD",
                {"kcal": 48, "protein_g": 0.7, "carbs_g": 10.0, "fat_g": 0.3, "fiber_g": 3.0},
                [300, 500])

        # ===== NEUE ZUTATEN (guenstig & schnell) =====

        # --- Getreide (neu) ---
        add_ing("couscous", "Couscous", "Getreide", "g", "MHD",
                {"kcal": 356, "protein_g": 12.0, "carbs_g": 72.0, "fat_g": 1.5, "fiber_g": 2.0},
                [500])
        add_ing("instant_nudeln", "Instant-Nudeln", "Getreide", "g", "MHD",
                {"kcal": 360, "protein_g": 8.0, "carbs_g": 70.0, "fat_g": 6.0, "fiber_g": 2.0},
                [300, 500])
        add_ing("brot", "Brot (Mischbrot)", "Getreide", "piece", "FRESH",
                {"kcal": 220, "protein_g": 7.0, "carbs_g": 42.0, "fat_g": 1.5, "fiber_g": 4.0},
                [1])

        # --- Protein (neu) ---
        add_ing("tofu", "Tofu", "Protein", "g", "FRESH",
                {"kcal": 76, "protein_g": 8.0, "carbs_g": 1.9, "fat_g": 4.8, "fiber_g": 0.3},
                [200, 400])

        # --- Konserven (neu) ---
        add_ing("kichererbsen", "Kichererbsen (Dose)", "Konserve", "g", "MHD",
                {"kcal": 119, "protein_g": 7.0, "carbs_g": 17.0, "fat_g": 2.6, "fiber_g": 5.0},
                [400])
        add_ing("mais_dose", "Mais (Dose)", "Konserve", "g", "MHD",
                {"kcal": 81, "protein_g": 2.7, "carbs_g": 16.0, "fat_g": 1.2, "fiber_g": 2.0},
                [285, 400])
        add_ing("passierte_tomaten", "Passierte Tomaten", "Konserve", "ml", "MHD",
                {"kcal": 24, "protein_g": 1.0, "carbs_g": 4.2, "fat_g": 0.1, "fiber_g": 1.0},
                [500])

        # --- Gemuese (neu) ---
        add_ing("tk_erbsen", "Tiefkuehl-Erbsen", "Gemuese", "g", "MHD",
                {"kcal": 81, "protein_g": 5.4, "carbs_g": 14.0, "fat_g": 0.4, "fiber_g": 5.0},
                [450, 750])
        add_ing("zucchini", "Zucchini", "Gemuese", "g", "FRESH",
                {"kcal": 17, "protein_g": 1.2, "carbs_g": 3.1, "fat_g": 0.3, "fiber_g": 1.0},
                [1])
        add_ing("knoblauch", "Knoblauch", "Gemuese", "g", "MHD",
                {"kcal": 149, "protein_g": 6.4, "carbs_g": 33.0, "fat_g": 0.5, "fiber_g": 2.1},
                [1])
        add_ing("gurke", "Gurke", "Gemuese", "piece", "FRESH",
                {"kcal": 12, "protein_g": 0.7, "carbs_g": 1.8, "fat_g": 0.1, "fiber_g": 0.5},
                [1])

        # --- Milchprodukt (neu) ---
        add_ing("naturjoghurt", "Naturjoghurt", "Milchprodukt", "g", "FRESH",
                {"kcal": 61, "protein_g": 3.5, "carbs_g": 4.7, "fat_g": 3.2, "fiber_g": 0},
                [500])

        # --- Gewuerze & Sonstiges (neu) ---
        add_ing("honig", "Honig", "Sonstiges", "g", "NO_EXPIRY",
                {"kcal": 304, "protein_g": 0.3, "carbs_g": 82.0, "fat_g": 0, "fiber_g": 0},
                [500])
        add_ing("sojasauce", "Sojasauce", "Gewuerz", "ml", "MHD",
                {"kcal": 53, "protein_g": 5.0, "carbs_g": 6.0, "fat_g": 0, "fiber_g": 0},
                [250, 500])
        add_ing("senf", "Senf", "Gewuerz", "g", "MHD",
                {"kcal": 66, "protein_g": 4.4, "carbs_g": 3.9, "fat_g": 3.3, "fiber_g": 3.0},
                [200])

        db.flush()

        # ---------------------------------------------------------------
        # Recipes
        # ---------------------------------------------------------------
        def make_recipe(name, cook_time, tags, nutrition_pp, ingredient_list, instructions=None):
            r = Recipe(name=name, portions_default=1, cook_time_min=cook_time)
            r.tags = tags
            r.nutrition_per_portion = nutrition_pp
            r.instructions = instructions
            db.add(r)
            db.flush()
            for ing_key, amount, unit, optional in ingredient_list:
                ri = RecipeIngredient(
                    recipe_id=r.id,
                    ingredient_id=ingredients[ing_key].id,
                    amount=amount,
                    unit=unit,
                    optional_bool=optional,
                )
                db.add(ri)
            return r

        # ===== FRUEHSTUECK (450-600 kcal) =====

        make_recipe("Overnight Oats", 5, ["fruehstueck", "schnell", "meal-prep"],
            {"kcal": 480, "protein_g": 26, "carbs_g": 68, "fat_g": 10, "fiber_g": 8},
            [("haferflocken", 80, "g", False), ("skyr", 200, "g", False),
             ("banane", 1, "piece", False), ("erdnussbutter", 15, "g", True)],
            "Haferflocken mit Skyr in ein Glas schichten. Banane in Scheiben schneiden und dazugeben. Ueber Nacht im Kuehlschrank ziehen lassen.")

        make_recipe("Ruehrei mit Toast", 10, ["fruehstueck", "high-protein"],
            {"kcal": 550, "protein_g": 32, "carbs_g": 38, "fat_g": 28, "fiber_g": 4,
             "zinc_mg": 2.0, "vitamin_d_iu": 120, "iron_mg": 2.5},
            [("eier", 3, "piece", False), ("butter", 10, "g", False),
             ("vollkorntoast", 2, "piece", False), ("kaese", 20, "g", True)],
            "Butter in der Pfanne erhitzen. Eier verquirlen, wuerzen und bei mittlerer Hitze stocken lassen. Toast toasten und mit Ruehrei servieren.")

        make_recipe("Protein-Porridge", 8, ["fruehstueck", "high-protein", "schnell"],
            {"kcal": 520, "protein_g": 35, "carbs_g": 62, "fat_g": 12, "fiber_g": 8},
            [("haferflocken", 80, "g", False), ("milch", 250, "ml", False),
             ("banane", 1, "piece", False), ("erdnussbutter", 15, "g", False)],
            "Haferflocken mit Milch aufkochen, 3 Min koecheln lassen. Banane zerquetschen und unterruehren. Erdnussbutter obendrauf geben.")

        make_recipe("Skyr-Bowl mit Beeren", 5, ["fruehstueck", "schnell", "high-protein"],
            {"kcal": 450, "protein_g": 40, "carbs_g": 52, "fat_g": 6, "fiber_g": 6},
            [("skyr", 300, "g", False), ("haferflocken", 40, "g", False),
             ("tk_beeren", 100, "g", False), ("banane", 1, "piece", True)],
            "Skyr in eine Schuessel geben. Haferflocken und TK-Beeren dazu, kurz umruehren. Optional Banane in Scheiben dazu.")

        make_recipe("Bananen-Pancakes", 15, ["fruehstueck"],
            {"kcal": 510, "protein_g": 24, "carbs_g": 66, "fat_g": 16, "fiber_g": 6},
            [("banane", 2, "piece", False), ("eier", 2, "piece", False),
             ("haferflocken", 60, "g", False), ("butter", 10, "g", False)],
            "Bananen zerquetschen, Eier und Haferflocken dazugeben und zu einem Teig verruehren. In Butter kleine Pancakes von beiden Seiten goldbraun braten.")

        # ===== HAUPTMAHLZEITEN (600-800 kcal) =====

        make_recipe("Haehnchen-Reis-Brokkoli", 25, ["mittagessen", "abendessen", "high-protein", "meal-prep"],
            {"kcal": 680, "protein_g": 52, "carbs_g": 65, "fat_g": 16, "fiber_g": 5,
             "vitamin_c_mg": 90, "calcium_mg": 50, "iron_mg": 1.5, "zinc_mg": 2.0},
            [("haehnchen", 200, "g", False), ("reis", 120, "g", False),
             ("brokkoli", 200, "g", False), ("olivenoel", 10, "ml", False)],
            "Reis kochen. Haehnchen wuerzen und in Olivenoel anbraten. Brokkoli dazu geben und 5 Min mitbraten. Mit Reis servieren.")

        make_recipe("Pasta Bolognese", 30, ["mittagessen", "abendessen", "meal-prep"],
            {"kcal": 720, "protein_g": 40, "carbs_g": 72, "fat_g": 26, "fiber_g": 5},
            [("nudeln", 120, "g", False), ("hackfleisch", 150, "g", False),
             ("tomaten_dose", 200, "g", False), ("zwiebeln", 80, "g", False),
             ("olivenoel", 10, "ml", False), ("kaese", 15, "g", True)],
            "Zwiebeln in Olivenoel anduensten. Hackfleisch dazu und kroemelig braten. Tomaten dazu, 15 Min koecheln. Nudeln kochen und mit Sauce servieren.")

        make_recipe("Thunfisch-Reispfanne", 20, ["mittagessen", "abendessen", "high-protein", "schnell", "fisch"],
            {"kcal": 600, "protein_g": 44, "carbs_g": 62, "fat_g": 14, "fiber_g": 3,
             "omega3_g": 1.5, "zinc_mg": 1.2, "vitamin_d_iu": 40},
            [("thunfisch", 150, "g", False), ("reis", 120, "g", False),
             ("tk_gemuese", 150, "g", False), ("olivenoel", 10, "ml", False)],
            "Reis kochen. TK-Gemuese in Olivenoel anbraten. Thunfisch abtropfen lassen und dazugeben. Mit Reis vermischen und wuerzen.")

        make_recipe("Putenbrust-Wrap", 15, ["mittagessen", "schnell", "high-protein"],
            {"kcal": 640, "protein_g": 48, "carbs_g": 56, "fat_g": 22, "fiber_g": 4},
            [("tortilla", 2, "piece", False), ("putenbrust", 200, "g", False),
             ("paprika", 1, "piece", False), ("kaese", 30, "g", False),
             ("skyr", 50, "g", True)],
            "Putenbrust in Streifen schneiden und anbraten. Paprika klein schneiden. Tortillas belegen mit Pute, Paprika und Kaese, einrollen.")

        make_recipe("Chili con Carne", 30, ["mittagessen", "abendessen", "meal-prep"],
            {"kcal": 700, "protein_g": 42, "carbs_g": 58, "fat_g": 28, "fiber_g": 12},
            [("hackfleisch", 150, "g", False), ("kidneybohnen", 200, "g", False),
             ("tomaten_dose", 200, "g", False), ("reis", 80, "g", False),
             ("zwiebeln", 80, "g", False), ("olivenoel", 10, "ml", False)],
            "Zwiebeln anbraten, Hackfleisch dazu. Bohnen und Tomaten dazugeben, wuerzen. 20 Min koecheln lassen. Reis separat kochen.")

        make_recipe("Lachs mit Kartoffeln", 25, ["mittagessen", "abendessen", "high-protein", "fisch"],
            {"kcal": 720, "protein_g": 44, "carbs_g": 52, "fat_g": 34, "fiber_g": 5,
             "omega3_g": 2.5, "vitamin_d_iu": 120, "calcium_mg": 45, "vitamin_c_mg": 60},
            [("lachs", 200, "g", False), ("kartoffeln", 300, "g", False),
             ("brokkoli", 150, "g", False), ("olivenoel", 10, "ml", False)],
            "Kartoffeln schaelen, vierteln und kochen. Lachs wuerzen und in Olivenoel braten. Brokkoli daempfen. Zusammen servieren.")

        make_recipe("Gemuese-Curry mit Reis", 25, ["mittagessen", "abendessen", "vegetarisch"],
            {"kcal": 650, "protein_g": 16, "carbs_g": 76, "fat_g": 28, "fiber_g": 8},
            [("tk_gemuese", 300, "g", False), ("kokosmilch", 150, "ml", False),
             ("reis", 120, "g", False), ("zwiebeln", 80, "g", False)],
            "Zwiebeln anduensten. TK-Gemuese dazu, kurz mitbraten. Kokosmilch dazugiessen und 10 Min koecheln. Reis separat kochen.")

        make_recipe("Spaghetti Carbonara", 20, ["mittagessen", "abendessen"],
            {"kcal": 780, "protein_g": 34, "carbs_g": 68, "fat_g": 38, "fiber_g": 3},
            [("nudeln", 120, "g", False), ("speck", 80, "g", False),
             ("eier", 2, "piece", False), ("kaese", 30, "g", False),
             ("sahne", 50, "ml", False)],
            "Nudeln kochen. Speck kross braten. Eier, Kaese und Sahne verquirlen. Nudeln abgiessen, Speck und Ei-Mix unterheben, sofort servieren.")

        make_recipe("Linsensuppe mit Brot", 25, ["mittagessen", "abendessen", "vegetarisch", "meal-prep"],
            {"kcal": 580, "protein_g": 32, "carbs_g": 74, "fat_g": 12, "fiber_g": 14,
             "iron_mg": 6.0, "zinc_mg": 2.5, "magnesium_mg": 60},
            [("linsen_dose", 300, "g", False), ("tomaten_dose", 200, "g", False),
             ("zwiebeln", 80, "g", False), ("vollkorntoast", 2, "piece", False),
             ("olivenoel", 10, "ml", False)],
            "Zwiebeln in Olivenoel anduensten. Linsen und Tomaten dazu, 15 Min koecheln. Wuerzen und mit Toast servieren.")

        make_recipe("Kartoffel-Hackfleisch-Pfanne", 25, ["mittagessen", "abendessen"],
            {"kcal": 690, "protein_g": 38, "carbs_g": 52, "fat_g": 32, "fiber_g": 5},
            [("kartoffeln", 300, "g", False), ("hackfleisch", 150, "g", False),
             ("zwiebeln", 80, "g", False), ("paprika", 1, "piece", False),
             ("olivenoel", 10, "ml", False)],
            "Kartoffeln wuerfeln und in Olivenoel anbraten. Hackfleisch, Zwiebeln und Paprika dazu, 10 Min braten. Wuerzen und servieren.")

        make_recipe("Omelette mit Gemuese", 12, ["fruehstueck", "mittagessen", "schnell", "high-protein"],
            {"kcal": 480, "protein_g": 32, "carbs_g": 8, "fat_g": 34, "fiber_g": 3},
            [("eier", 4, "piece", False), ("tk_gemuese", 100, "g", False),
             ("kaese", 30, "g", False), ("olivenoel", 10, "ml", False)],
            "Eier verquirlen und wuerzen. In Olivenoel giessen, TK-Gemuese drauf verteilen. Kaese drueber, zuklappen wenn fest.")

        make_recipe("Puten-Reis-Bowl", 20, ["mittagessen", "abendessen", "high-protein", "meal-prep"],
            {"kcal": 620, "protein_g": 50, "carbs_g": 66, "fat_g": 12, "fiber_g": 4},
            [("putenbrust", 200, "g", False), ("reis", 120, "g", False),
             ("tk_gemuese", 150, "g", False), ("olivenoel", 8, "ml", False)],
            "Reis kochen. Putenbrust wuerzen und in Olivenoel braten. TK-Gemuese anbraten. Alles in einer Bowl anrichten.")

        make_recipe("Nudelpfanne mit Haehnchen", 20, ["mittagessen", "abendessen", "schnell"],
            {"kcal": 700, "protein_g": 46, "carbs_g": 68, "fat_g": 22, "fiber_g": 4},
            [("nudeln", 120, "g", False), ("haehnchen", 180, "g", False),
             ("paprika", 1, "piece", False), ("olivenoel", 15, "ml", False),
             ("kaese", 15, "g", True)],
            "Nudeln kochen. Haehnchen in Streifen schneiden und anbraten. Paprika dazu. Nudeln unterheben und wuerzen.")

        make_recipe("Spinat-Lachs-Kartoffeln", 25, ["mittagessen", "abendessen", "high-protein", "fisch"],
            {"kcal": 680, "protein_g": 42, "carbs_g": 46, "fat_g": 32, "fiber_g": 5,
             "omega3_g": 2.2, "iron_mg": 4.0, "magnesium_mg": 90, "vitamin_d_iu": 100},
            [("lachs", 180, "g", False), ("kartoffeln", 250, "g", False),
             ("blattspinat", 150, "g", False), ("butter", 10, "g", False)],
            "Kartoffeln kochen. Lachs in Butter braten. Blattspinat auftauen und erwaermen. Zusammen anrichten.")

        make_recipe("Hackfleisch-Nudeln", 20, ["mittagessen", "abendessen", "schnell"],
            {"kcal": 740, "protein_g": 42, "carbs_g": 70, "fat_g": 28, "fiber_g": 4},
            [("nudeln", 120, "g", False), ("hackfleisch", 150, "g", False),
             ("tomaten_dose", 150, "g", False), ("olivenoel", 10, "ml", False)],
            "Nudeln kochen. Hackfleisch in Olivenoel anbraten, Tomaten dazu und 10 Min koecheln. Ueber die Nudeln geben.")

        make_recipe("Reis mit Ei und Gemuese", 15, ["mittagessen", "schnell", "vegetarisch"],
            {"kcal": 560, "protein_g": 22, "carbs_g": 68, "fat_g": 18, "fiber_g": 4},
            [("reis", 120, "g", False), ("eier", 2, "piece", False),
             ("tk_gemuese", 150, "g", False), ("olivenoel", 10, "ml", False)],
            "Reis kochen. TK-Gemuese in Olivenoel anbraten. Eier dazuschlagen und verrruehren. Mit Reis servieren.")

        # ===== SNACKS (200-350 kcal) =====

        make_recipe("Protein Shake", 3, ["snack", "schnell", "high-protein"],
            {"kcal": 300, "protein_g": 32, "carbs_g": 36, "fat_g": 4, "fiber_g": 3},
            [("skyr", 200, "g", False), ("banane", 1, "piece", False),
             ("haferflocken", 30, "g", False)],
            "Alle Zutaten in einen Mixer geben und glatt puerieren.")

        make_recipe("Quark mit Beeren", 3, ["snack", "schnell", "high-protein"],
            {"kcal": 250, "protein_g": 32, "carbs_g": 20, "fat_g": 2, "fiber_g": 4},
            [("magerquark", 250, "g", False), ("tk_beeren", 100, "g", False)],
            "Magerquark in eine Schuessel geben, TK-Beeren darauf verteilen. Kurz antauen lassen.")

        make_recipe("Erdnussbutter-Toast", 5, ["snack", "schnell"],
            {"kcal": 330, "protein_g": 14, "carbs_g": 32, "fat_g": 18, "fiber_g": 4},
            [("vollkorntoast", 2, "piece", False), ("erdnussbutter", 25, "g", False)],
            "Toast toasten und mit Erdnussbutter bestreichen.")

        make_recipe("Gemuese-Omelette (klein)", 8, ["snack", "schnell", "high-protein"],
            {"kcal": 280, "protein_g": 20, "carbs_g": 4, "fat_g": 20, "fiber_g": 2},
            [("eier", 2, "piece", False), ("tk_gemuese", 80, "g", False),
             ("olivenoel", 5, "ml", False)],
            "Eier verquirlen. In Olivenoel giessen, TK-Gemuese drauf verteilen. Bei mittlerer Hitze stocken lassen.")

        # ===== NEUE REZEPTE (guenstig & schnell) =====

        # --- Fruehstueck (5 neue) ---

        make_recipe("Joghurt mit Haferflocken und Honig", 5,
            ["fruehstueck", "schnell", "vegetarisch"],
            {"kcal": 350, "protein_g": 12, "carbs_g": 58, "fat_g": 8, "fiber_g": 5},
            [("naturjoghurt", 200, "g", False), ("haferflocken", 50, "g", False),
             ("honig", 15, "g", False)],
            "Joghurt mit Haferflocken vermischen und Honig daruebertraeufen.")

        make_recipe("Ruehrei-Wrap", 10,
            ["fruehstueck", "schnell"],
            {"kcal": 480, "protein_g": 24, "carbs_g": 42, "fat_g": 22, "fiber_g": 3},
            [("eier", 2, "piece", False), ("tortilla", 1, "piece", False),
             ("kaese", 20, "g", False), ("butter", 5, "g", False)],
            "Eier in Butter ruehren. Tortilla erwaermen, mit Ruehrei und Kaese fuellen, einrollen.")

        make_recipe("Porridge mit Beeren", 8,
            ["fruehstueck", "schnell", "vegetarisch"],
            {"kcal": 420, "protein_g": 14, "carbs_g": 68, "fat_g": 10, "fiber_g": 8},
            [("haferflocken", 80, "g", False), ("milch", 250, "ml", False),
             ("tk_beeren", 80, "g", False), ("honig", 10, "g", True)],
            "Haferflocken mit Milch aufkochen, 3 Min koecheln lassen. TK-Beeren darauf verteilen.")

        make_recipe("Brot mit Erdnussbutter und Banane", 3,
            ["fruehstueck", "schnell", "vegetarisch"],
            {"kcal": 400, "protein_g": 12, "carbs_g": 50, "fat_g": 18, "fiber_g": 5},
            [("brot", 2, "piece", False), ("erdnussbutter", 25, "g", False),
             ("banane", 1, "piece", False)],
            "Brot mit Erdnussbutter bestreichen. Banane in Scheiben schneiden und darauf legen.")

        make_recipe("Couscous-Fruehstuecksbowl", 8,
            ["fruehstueck", "schnell", "vegetarisch"],
            {"kcal": 450, "protein_g": 14, "carbs_g": 72, "fat_g": 12, "fiber_g": 4},
            [("couscous", 80, "g", False), ("milch", 150, "ml", False),
             ("banane", 1, "piece", False), ("honig", 15, "g", False)],
            "Couscous mit heisser Milch uebergiessen, 5 Min quellen lassen. Banane schneiden und mit Honig servieren.")

        # --- Hauptmahlzeiten (10 neue) ---

        make_recipe("Couscous-Gemuesepfanne", 15,
            ["mittagessen", "abendessen", "vegetarisch", "schnell"],
            {"kcal": 550, "protein_g": 16, "carbs_g": 80, "fat_g": 14, "fiber_g": 6},
            [("couscous", 100, "g", False), ("tk_gemuese", 200, "g", False),
             ("zwiebeln", 60, "g", False), ("olivenoel", 10, "ml", False)],
            "Couscous mit heissem Wasser quellen lassen. Zwiebeln und TK-Gemuese in Olivenoel anbraten. Couscous unterheben.")

        make_recipe("Gebratener Reis mit Ei", 15,
            ["mittagessen", "abendessen", "vegetarisch", "schnell"],
            {"kcal": 520, "protein_g": 18, "carbs_g": 70, "fat_g": 16, "fiber_g": 3},
            [("reis", 120, "g", False), ("eier", 2, "piece", False),
             ("tk_gemuese", 100, "g", False), ("sojasauce", 15, "ml", False),
             ("olivenoel", 10, "ml", False)],
            "Reis kochen. In Olivenoel TK-Gemuese anbraten, Reis dazu. Eier dazuschlagen und unterruehren. Mit Sojasauce abschmecken.")

        make_recipe("Nudeln mit Knoblauch-Oel", 12,
            ["mittagessen", "abendessen", "vegetarisch", "schnell"],
            {"kcal": 580, "protein_g": 14, "carbs_g": 72, "fat_g": 24, "fiber_g": 3},
            [("nudeln", 120, "g", False), ("knoblauch", 10, "g", False),
             ("olivenoel", 20, "ml", False), ("kaese", 15, "g", True)],
            "Nudeln kochen. Knoblauch fein schneiden und in Olivenoel goldbraun anbraten. Nudeln dazu schwenken.")

        make_recipe("Kichererbsen-Curry", 20,
            ["mittagessen", "abendessen", "vegetarisch", "meal-prep"],
            {"kcal": 600, "protein_g": 22, "carbs_g": 68, "fat_g": 24, "fiber_g": 12,
             "iron_mg": 5.0, "magnesium_mg": 70, "zinc_mg": 2.0, "calcium_mg": 60},
            [("kichererbsen", 300, "g", False), ("kokosmilch", 150, "ml", False),
             ("passierte_tomaten", 200, "ml", False), ("zwiebeln", 80, "g", False),
             ("reis", 80, "g", False)],
            "Zwiebeln anduensten. Kichererbsen, Tomaten und Kokosmilch dazu, wuerzen. 15 Min koecheln. Mit Reis servieren.")

        make_recipe("Tofu-Gemuesepfanne mit Reis", 20,
            ["mittagessen", "abendessen", "vegetarisch"],
            {"kcal": 550, "protein_g": 24, "carbs_g": 66, "fat_g": 18, "fiber_g": 5},
            [("tofu", 200, "g", False), ("reis", 100, "g", False),
             ("tk_gemuese", 200, "g", False), ("sojasauce", 15, "ml", False),
             ("olivenoel", 10, "ml", False)],
            "Tofu wuerfeln und in Olivenoel kross braten. TK-Gemuese dazu, mit Sojasauce wuerzen. Mit Reis servieren.")

        make_recipe("Erbsen-Kartoffel-Eintopf", 20,
            ["mittagessen", "abendessen", "vegetarisch", "meal-prep"],
            {"kcal": 480, "protein_g": 18, "carbs_g": 62, "fat_g": 14, "fiber_g": 10},
            [("kartoffeln", 300, "g", False), ("tk_erbsen", 200, "g", False),
             ("zwiebeln", 80, "g", False), ("olivenoel", 10, "ml", False)],
            "Kartoffeln wuerfeln, mit Zwiebeln anbraten. Erbsen und Wasser dazu, 15 Min koecheln bis weich.")

        make_recipe("Thunfisch-Nudeln", 15,
            ["mittagessen", "abendessen", "schnell", "high-protein", "fisch"],
            {"kcal": 620, "protein_g": 42, "carbs_g": 70, "fat_g": 14, "fiber_g": 3,
             "omega3_g": 1.3, "zinc_mg": 1.0},
            [("nudeln", 120, "g", False), ("thunfisch", 150, "g", False),
             ("passierte_tomaten", 150, "ml", False), ("knoblauch", 5, "g", False),
             ("olivenoel", 10, "ml", False)],
            "Nudeln kochen. Knoblauch in Olivenoel anbraten, Tomaten und Thunfisch dazu. Kurz koecheln, ueber die Nudeln geben.")

        make_recipe("Wrap mit Haehnchen und Gemuese", 10,
            ["mittagessen", "schnell", "high-protein"],
            {"kcal": 580, "protein_g": 40, "carbs_g": 48, "fat_g": 20, "fiber_g": 4},
            [("tortilla", 2, "piece", False), ("haehnchen", 150, "g", False),
             ("paprika", 1, "piece", False), ("kaese", 20, "g", True)],
            "Haehnchen in Streifen braten. Paprika schneiden. Tortillas mit Haehnchen und Gemuese fuellen, einrollen.")

        make_recipe("Hackfleisch-Couscous", 15,
            ["mittagessen", "abendessen", "schnell"],
            {"kcal": 650, "protein_g": 36, "carbs_g": 64, "fat_g": 24, "fiber_g": 4},
            [("hackfleisch", 150, "g", False), ("couscous", 100, "g", False),
             ("zwiebeln", 60, "g", False), ("passierte_tomaten", 100, "ml", False),
             ("olivenoel", 10, "ml", False)],
            "Hackfleisch mit Zwiebeln anbraten. Tomaten dazu. Couscous mit heissem Wasser quellen lassen und unterruehren.")

        make_recipe("Zucchini-Nudelpfanne", 15,
            ["mittagessen", "abendessen", "vegetarisch", "schnell"],
            {"kcal": 520, "protein_g": 16, "carbs_g": 68, "fat_g": 18, "fiber_g": 4},
            [("nudeln", 120, "g", False), ("zucchini", 200, "g", False),
             ("knoblauch", 5, "g", False), ("olivenoel", 15, "ml", False),
             ("kaese", 15, "g", True)],
            "Nudeln kochen. Zucchini in Scheiben schneiden und mit Knoblauch in Olivenoel anbraten. Nudeln unterheben.")

        # --- Snacks (5 neue) ---

        make_recipe("Joghurt mit Honig", 3,
            ["snack", "schnell", "vegetarisch"],
            {"kcal": 200, "protein_g": 8, "carbs_g": 32, "fat_g": 5, "fiber_g": 0},
            [("naturjoghurt", 200, "g", False), ("honig", 20, "g", False)],
            "Joghurt in eine Schuessel geben und Honig daruebertraeufen.")

        make_recipe("Couscous-Salat", 10,
            ["snack", "meal-prep", "vegetarisch"],
            {"kcal": 300, "protein_g": 10, "carbs_g": 48, "fat_g": 8, "fiber_g": 3},
            [("couscous", 60, "g", False), ("gurke", 1, "piece", False),
             ("paprika", 1, "piece", False), ("olivenoel", 10, "ml", False)],
            "Couscous mit heissem Wasser quellen lassen. Gurke und Paprika klein schneiden, unterheben. Mit Olivenoel und Gewuerzen anmachen.")

        make_recipe("Mais-Thunfisch-Salat", 5,
            ["snack", "schnell", "high-protein"],
            {"kcal": 280, "protein_g": 28, "carbs_g": 20, "fat_g": 8, "fiber_g": 2},
            [("thunfisch", 100, "g", False), ("mais_dose", 100, "g", False)],
            "Thunfisch abtropfen lassen, mit Mais vermischen. Nach Geschmack wuerzen.")

        make_recipe("Brot mit Kaese", 3,
            ["snack", "schnell"],
            {"kcal": 300, "protein_g": 14, "carbs_g": 34, "fat_g": 12, "fiber_g": 3},
            [("brot", 2, "piece", False), ("kaese", 30, "g", False)],
            "Brot mit Kaese belegen. Optional kurz in den Ofen fuer warmen Kaese.")

        make_recipe("Kichererbsen-Snack", 5,
            ["snack", "vegetarisch", "schnell"],
            {"kcal": 250, "protein_g": 12, "carbs_g": 30, "fat_g": 8, "fiber_g": 8},
            [("kichererbsen", 200, "g", False), ("olivenoel", 5, "ml", False)],
            "Kichererbsen abtropfen lassen, mit Olivenoel und Gewuerzen in der Pfanne roesten bis knusprig.")

        db.flush()

        # ---------------------------------------------------------------
        # User Profile (singleton)
        # ---------------------------------------------------------------
        profile = UserProfile(
            id=1,
            height_cm=180.0,
            weight_kg=80.0,
            sex="male",
            activity_level="moderate",
            target_weight_kg=75.0,
        )
        db.add(profile)

        # ---------------------------------------------------------------
        # Goal Phase
        # ---------------------------------------------------------------
        gp = GoalPhase(
            name="Defi",
            start_date=today - timedelta(days=14),
            is_active=True,
        )
        gp.macro_targets = {
            "protein_g_per_kg_min": 2.0,
            "fat_g_per_kg_min": 0.8,
            "carb_strategy": "moderate",
        }
        gp.scoring_weights = {
            "w_macro": 0.35,
            "w_mhd": 0.25,
            "w_eff": 0.15,
            "w_slot": 0.10,
            "w_variety": 0.15,
        }
        db.add(gp)

        # ---------------------------------------------------------------
        # Body Metric
        # ---------------------------------------------------------------
        bm = BodyMetric(date=today, weight_kg=80.0)
        db.add(bm)

        # ---------------------------------------------------------------
        # Shopping Rules
        # ---------------------------------------------------------------
        rules = [
            ("reis", 500, "g", 1000, "NORMAL"),
            ("nudeln", 500, "g", 500, "NORMAL"),
            ("haferflocken", 300, "g", 500, "NORMAL"),
            ("skyr", 200, "g", 450, "CRITICAL"),
            ("eier", 4, "piece", 10, "CRITICAL"),
            ("haehnchen", 400, "g", 400, "NORMAL"),
            ("olivenoel", 200, "ml", 500, "NORMAL"),
        ]
        for key, min_s, unit, target, prio in rules:
            sr = ShoppingRule(
                ingredient_id=ingredients[key].id,
                min_stock=min_s, unit=unit,
                target_stock=target, priority=prio,
            )
            db.add(sr)

        # ---------------------------------------------------------------
        # Supplements
        # ---------------------------------------------------------------
        supplements_data = [
            # (name, dose, timing, order, category, condition_tag, nutrition)
            ("Whey Protein", "30g", "morgens", 0, "daily", None,
             {"kcal": 120, "protein_g": 24, "carbs_g": 3, "fat_g": 1.5}),
            ("Kreatin", "5g", "morgens", 1, "daily", None, None),
            ("Ashwagandha", "600mg", "morgens", 2, "daily", None, None),
            ("Brahmi", "300mg", "morgens", 3, "daily", None, None),
            ("Loewenmaehne", "500mg", "morgens", 4, "daily", None, None),
            ("Vitamin D3", "5000 IU", "morgens", 5, "daily", None,
             {"vitamin_d_iu": 5000}),
            ("Omega-3", "2g", "morgens", 6, "conditional", "fisch",
             {"omega3_g": 2, "fat_g": 2, "kcal": 18}),
            ("Melatonin", "1mg", "abends", 10, "daily", None, None),
            ("Magnesium", "400mg", "abends", 11, "daily", None,
             {"magnesium_mg": 400}),
        ]
        for name, dose, timing, order, category, condition_tag, nutrition in supplements_data:
            s = Supplement(
                name=name, dose=dose, timing=timing,
                active=True, sort_order=order,
                category=category, condition_tag=condition_tag,
            )
            if nutrition:
                s.nutrition = nutrition
            db.add(s)

        db.commit()

        n_ing = len(ingredients)
        n_rec = db.query(Recipe).count()
        n_sup = db.query(Supplement).count()
        print(f"Seed abgeschlossen: {n_ing} Zutaten, {n_rec} Rezepte, 1 Profil, "
              f"1 Phase, 1 BodyMetric, {len(rules)} Rules, {n_sup} Supplements.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
