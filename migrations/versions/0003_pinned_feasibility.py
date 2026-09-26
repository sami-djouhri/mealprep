"""pinned flag, feasibility status, missing ingredients cache

Revision ID: 0003_pinned_feasibility
Revises: 0002_lager_profile
Create Date: 2026-03-01 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_pinned_feasibility"
down_revision: Union[str, None] = "0002_lager_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("meal_slot") as batch_op:
        batch_op.add_column(
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "feasibility_status",
                sa.String(length=20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column("missing_ingredients_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("meal_slot") as batch_op:
        batch_op.drop_column("missing_ingredients_json")
        batch_op.drop_column("feasibility_status")
        batch_op.drop_column("pinned")
