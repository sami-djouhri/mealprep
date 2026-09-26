"""allergens_json on ingredient table

Revision ID: 0009_ingredient_allergens
Revises: 0008_add_indexes
Create Date: 2026-03-13 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009_ingredient_allergens"
down_revision: Union[str, None] = "0008_add_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ingredient") as batch_op:
        batch_op.add_column(sa.Column("allergens_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ingredient") as batch_op:
        batch_op.drop_column("allergens_json")
