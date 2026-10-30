"""supplement nutrition_json column

Revision ID: 0006_supplement_nutrition
Revises: 0005_adhoc_micronutrients
Create Date: 2026-03-02 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_supplement_nutrition"
down_revision: Union[str, None] = "0005_adhoc_micronutrients"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("supplement") as batch_op:
        batch_op.add_column(sa.Column("nutrition_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("supplement") as batch_op:
        batch_op.drop_column("nutrition_json")
