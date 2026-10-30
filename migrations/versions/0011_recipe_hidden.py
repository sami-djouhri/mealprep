"""recipe_hidden: per-Nutzer ausgeblendete globale Rezepte ("nicht vorschlagen").

Revision ID: 0011_recipe_hidden
Revises: 0010_multitenant
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_recipe_hidden"
down_revision = "0010_multitenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipe_hidden",
        sa.Column("owner_sub", sa.String(128), primary_key=True),
        sa.Column(
            "recipe_id", sa.Integer, sa.ForeignKey("recipe.id"), primary_key=True
        ),
    )


def downgrade() -> None:
    op.drop_table("recipe_hidden")
