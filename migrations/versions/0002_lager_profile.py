"""lager integration, user profile, remove local stock

Revision ID: 0002_lager_profile
Revises: 7b5ed8aae308
Create Date: 2026-02-27 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_lager_profile"
down_revision: Union[str, None] = "7b5ed8aae308"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Drop old local-stock tables (order matters for FK constraints)
    op.drop_table("consumption_line")
    op.drop_table("consumption_event")
    op.drop_table("stock_batch")

    # 2) Add lager_product_id to ingredient
    op.add_column("ingredient", sa.Column("lager_product_id", sa.Integer(), nullable=True))

    # 3) Remove calendar_event_id from meal_slot (SQLite batch mode)
    with op.batch_alter_table("meal_slot") as batch_op:
        batch_op.drop_column("calendar_event_id")

    # 4) Extend body_metric
    op.add_column("body_metric", sa.Column("body_fat_pct", sa.Float(), nullable=True))
    op.add_column("body_metric", sa.Column("waist_cm", sa.Float(), nullable=True))

    # 5) Create user_profile table
    op.create_table(
        "user_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False, server_default="175.0"),
        sa.Column("weight_kg", sa.Float(), nullable=False, server_default="75.0"),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=10), nullable=False, server_default="male"),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("activity_level", sa.String(length=20), nullable=False, server_default="moderate"),
        sa.Column("waist_cm", sa.Float(), nullable=True),
        sa.Column("allergies_json", sa.Text(), nullable=True),
        sa.Column("intolerances_json", sa.Text(), nullable=True),
        sa.Column("target_weight_kg", sa.Float(), nullable=True),
        sa.Column("kcal_target_override", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("user_profile")

    op.drop_column("body_metric", "waist_cm")
    op.drop_column("body_metric", "body_fat_pct")

    with op.batch_alter_table("meal_slot") as batch_op:
        batch_op.add_column(sa.Column("calendar_event_id", sa.String(length=200), nullable=True))

    op.drop_column("ingredient", "lager_product_id")

    # Recreate dropped tables
    op.create_table(
        "stock_batch",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("location", sa.String(length=50), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("lot_note", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "consumption_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("ref_type", sa.String(length=50), nullable=True),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "consumption_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["stock_batch.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["consumption_event.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
