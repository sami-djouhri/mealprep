"""multi-tenant: owner_sub (strict + hybrid recipe) + Composite-Unique shopping_rule

Revision ID: 0010_multitenant
Revises: 0009_ingredient_allergens
Create Date: 2026-07-04

ingredient bleibt global. recipe/recipe_ingredient = HYBRID: owner_sub NULLABLE,
Bestandsrezepte bleiben NULL (= mitgelieferte globale Bibliothek). STRICT-Tabellen:
owner_sub NOT NULL, server_default=Owner backfillt Alt-Daten. shopping_rule:
UNIQUE(ingredient_id) -> (owner_sub, ingredient_id) via batch (ingredient global).
"""

import os

from alembic import op
import sqlalchemy as sa

revision = "0010_multitenant"
down_revision = "0009_ingredient_allergens"
branch_labels = None
depends_on = None

# Owner aller Alt-Daten. Kommt aus der Umgebung (DEFAULT_OWNER_SUB), nicht mehr
# aus dem Quelltext: die Kennung gehoert einem konkreten Menschen, und dieses
# Repo soll veroeffentlicht werden koennen (2026-09-05).
#
# Leer ist unbedenklich. Der Wert dient als server_default beim Hinzufuegen der
# NOT-NULL-Spalte, also der Bestandsuebernahme. Bei einer frischen Installation
# gibt es keinen Bestand, und neue Zeilen stempelt ohnehin das ORM
# (app/tenant.py, before_flush), nicht dieser Vorgabewert.
#
# ⚠️ Wer diese Migration auf einer BESTEHENDEN Datenbank zum ersten Mal faehrt,
# sollte DEFAULT_OWNER_SUB setzen, sonst gehoeren die Alt-Daten niemandem.
OWNER = os.environ.get("DEFAULT_OWNER_SUB", "")
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

STRICT_SIMPLE = (
    "goal_phase", "body_metric", "user_profile", "meal_slot", "intake_item",
    "shopping_list", "shopping_list_line", "supplement", "supplement_log",
)
HYBRID = ("recipe", "recipe_ingredient")


def upgrade() -> None:
    for tbl in STRICT_SIMPLE:
        with op.batch_alter_table(tbl) as b:
            b.add_column(sa.Column("owner_sub", sa.String(128), nullable=False, server_default=OWNER))
            b.create_index(f"ix_{tbl}_owner_sub", ["owner_sub"])

    # HYBRID: nullable, KEIN server_default -> Bestand bleibt NULL (global).
    for tbl in HYBRID:
        with op.batch_alter_table(tbl) as b:
            b.add_column(sa.Column("owner_sub", sa.String(128), nullable=True))
            b.create_index(f"ix_{tbl}_owner_sub", ["owner_sub"])

    # shopping_rule: unbenannte UNIQUE(ingredient_id) -> (owner_sub, ingredient_id)
    with op.batch_alter_table("shopping_rule", naming_convention=NAMING) as b:
        b.add_column(sa.Column("owner_sub", sa.String(128), nullable=False, server_default=OWNER))
        b.drop_constraint("uq_shopping_rule_ingredient_id", type_="unique")
        b.create_unique_constraint("uq_shopping_rule_owner_ingredient", ["owner_sub", "ingredient_id"])
        b.create_index("ix_shopping_rule_owner_sub", ["owner_sub"])


def downgrade() -> None:
    with op.batch_alter_table("shopping_rule", naming_convention=NAMING) as b:
        b.drop_constraint("uq_shopping_rule_owner_ingredient", type_="unique")
        b.create_unique_constraint("uq_shopping_rule_ingredient_id", ["ingredient_id"])
        b.drop_index("ix_shopping_rule_owner_sub")
        b.drop_column("owner_sub")
    for tbl in reversed(HYBRID):
        with op.batch_alter_table(tbl) as b:
            b.drop_index(f"ix_{tbl}_owner_sub")
            b.drop_column("owner_sub")
    for tbl in reversed(STRICT_SIMPLE):
        with op.batch_alter_table(tbl) as b:
            b.drop_index(f"ix_{tbl}_owner_sub")
            b.drop_column("owner_sub")
