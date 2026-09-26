"""shopping_list_line: Einkauf abhaken und in den Bestand buchen.

Revision ID: 0012_einkauf_abhaken
Revises: 0011_recipe_hidden

Drei Spalten, damit ein Haken nachvollziehbar bleibt:

- ``gekauft_am``: wann abgehakt wurde. NULL = offen.
- ``gekaufte_menge``: was tatsaechlich gekauft wurde. Das ist selten die
  geplante Menge, weil man Packungen kauft und keine Gramm.
- ``lager_stock_entry_id``: die Nummer des im Lager erzeugten
  Bestandseintrags. Ohne sie waere die Ruecknahme eines Hakens ein Suchen
  nach dem wahrscheinlich richtigen Eintrag, und das ist bei Vorraten
  derselben Sorte nicht entscheidbar.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_einkauf_abhaken"
down_revision = "0011_recipe_hidden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shopping_list_line") as b:
        b.add_column(sa.Column("gekauft_am", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("gekaufte_menge", sa.Float(), nullable=True))
        b.add_column(sa.Column("lager_stock_entry_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("shopping_list_line") as b:
        b.drop_column("lager_stock_entry_id")
        b.drop_column("gekaufte_menge")
        b.drop_column("gekauft_am")
