"""recipe instructions, supplement table, supplement_log table

Revision ID: 0004_instructions_supplements
Revises: 0003_pinned_feasibility
Create Date: 2026-03-01 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_instructions_supplements"
down_revision: Union[str, None] = "0003_pinned_feasibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recipe: add instructions column
    with op.batch_alter_table("recipe") as batch_op:
        batch_op.add_column(sa.Column("instructions", sa.Text(), nullable=True))

    # Supplement table
    op.create_table(
        "supplement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("dose", sa.String(50), nullable=False),
        sa.Column("timing", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    # SupplementLog table (daily check-off)
    op.create_table(
        "supplement_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "supplement_id",
            sa.Integer(),
            sa.ForeignKey("supplement.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("taken", sa.Boolean(), nullable=False, server_default="1"),
        sa.UniqueConstraint("supplement_id", "date", name="uq_supplement_log_day"),
    )


def downgrade() -> None:
    op.drop_table("supplement_log")
    op.drop_table("supplement")
    with op.batch_alter_table("recipe") as batch_op:
        batch_op.drop_column("instructions")
