"""Add indexes for query performance

Revision ID: 0008_add_indexes
Revises: 0007_excluded_ingredients
Create Date: 2026-03-05 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0008_add_indexes"
down_revision: Union[str, None] = "0007_excluded_ingredients"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_meal_slot_date", "meal_slot", ["date"])
    op.create_index("idx_meal_slot_status", "meal_slot", ["status"])
    op.create_index("idx_meal_slot_date_status", "meal_slot", ["date", "status"])
    op.create_index("idx_intake_item_timestamp", "intake_item", ["timestamp"])
    op.create_index("idx_recipe_ingredient_recipe_id", "recipe_ingredient", ["recipe_id"])
    op.create_index("idx_supplement_log_supplement_id", "supplement_log", ["supplement_id"])
    op.create_index("idx_supplement_log_date", "supplement_log", ["date"])


def downgrade() -> None:
    op.drop_index("idx_supplement_log_date")
    op.drop_index("idx_supplement_log_supplement_id")
    op.drop_index("idx_recipe_ingredient_recipe_id")
    op.drop_index("idx_intake_item_timestamp")
    op.drop_index("idx_meal_slot_date_status")
    op.drop_index("idx_meal_slot_status")
    op.drop_index("idx_meal_slot_date")
