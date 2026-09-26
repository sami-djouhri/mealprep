"""ad-hoc intake label, supplement category & condition_tag

Revision ID: 0005_adhoc_micronutrients
Revises: 0004_instructions_supplements
Create Date: 2026-03-01 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_adhoc_micronutrients"
down_revision: Union[str, None] = "0004_instructions_supplements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IntakeItem: label for ad-hoc meals
    with op.batch_alter_table("intake_item") as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(200), nullable=True))

    # Supplement: category (daily/conditional) and condition_tag
    with op.batch_alter_table("supplement") as batch_op:
        batch_op.add_column(
            sa.Column("category", sa.String(20), nullable=False, server_default="daily")
        )
        batch_op.add_column(
            sa.Column("condition_tag", sa.String(50), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("supplement") as batch_op:
        batch_op.drop_column("condition_tag")
        batch_op.drop_column("category")
    with op.batch_alter_table("intake_item") as batch_op:
        batch_op.drop_column("label")
