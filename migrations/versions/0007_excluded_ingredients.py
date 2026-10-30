"""excluded_ingredient_ids_json on user_profile

Revision ID: 0007_excluded_ingredients
Revises: 0006_supplement_nutrition
Create Date: 2026-03-02 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_excluded_ingredients"
down_revision: Union[str, None] = "0006_supplement_nutrition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_profile") as batch_op:
        batch_op.add_column(sa.Column("excluded_ingredient_ids_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_profile") as batch_op:
        batch_op.drop_column("excluded_ingredient_ids_json")
