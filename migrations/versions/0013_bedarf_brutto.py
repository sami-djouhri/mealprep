"""shopping_list_line: den ROHEN Bedarf mitfuehren, damit man ihn nachrechnen kann.

Revision ID: 0013_bedarf_brutto
Revises: 0012_einkauf_abhaken

★★ Warum das eine eigene Spalte braucht und kein Rechentrick reicht:

``needed_amount`` ist der Bedarf **abzueglich des Bestands zum Zeitpunkt der
Erzeugung**. Das ist eine Momentaufnahme. Wer sie beim Anzeigen noch einmal
gegen den aktuellen Bestand haelt, zieht denselben Vorrat zweimal ab und
kommt fast immer bei null heraus. Live gemessen am 2026-09-13: nach dem
Verknuepfen der Zutaten standen elf von dreiundzwanzig Zeilen auf "0 noch
noetig", obwohl sie auf der Liste standen.

Aus ``netto`` und dem heutigen Bestand laesst sich der richtige Wert nicht
zurueckrechnen, weil der Bestand von damals fehlt. Also wird der rohe Bedarf
mitgefuehrt, und das Nachrechnen findet genau einmal statt, beim Anzeigen.

NULL hat hier eine eigene Bedeutung: **nicht nachrechnen**. Zeilen, die aus
lagers eigener Vorschlagsrechnung stammen, tragen eine Zahl, die lager aus
Mindestbestand, Wochenverbrauch und Ablaufdatum gebildet hat. Sie noch einmal
gegen den Bestand zu halten hiesse, eine Rechnung zu wiederholen, deren
Eingangsdaten mealprep gar nicht hat.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_bedarf_brutto"
down_revision = "0012_einkauf_abhaken"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shopping_list_line") as b:
        b.add_column(sa.Column("bedarf_brutto", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("shopping_list_line") as b:
        b.drop_column("bedarf_brutto")
