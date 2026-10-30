"""Der Loeschweg dieses Dienstes: welche Tabelle in welcher Reihenfolge faellt.

Die Mechanik liegt in ``konto_mechanik.py`` (dort auch, warum es hier keine
Netzroute gibt und wie die vier Kopien abgeglichen werden). Hier steht nur, was
dieser Dienst ueber seine eigenen Tabellen weiss.

    docker exec -w /app mealprep python -m app.konto --sub X [--loeschen]

ZWEI ARTEN VON REZEPT, UND DIE UNTERSCHEIDUNG MACHT ``NULL``
===============================================================

``app/tenant.py`` kennt hier nicht eine, sondern zwei Modell-Listen, und der
Unterschied zaehlt genau an dieser Stelle:

* ``STRICT_MODELS`` gehoeren immer einem Mandanten.
* ``HYBRID_MODELS`` (``Recipe``, ``RecipeIngredient``) sind **beides**: der
  Seed-Katalog traegt durchgehend ``owner_sub NULL`` und gehoert allen, ein
  selbst angelegtes Rezept traegt den ``sub`` seines Mandanten.

Beide stehen deshalb in den Schritten, und zwar mit ``owner_sub = :sub``: diese
Bedingung trifft ``NULL`` nicht, der geteilte Katalog bleibt also unberuehrt.
Die naheliegende Abkuerzung ``DELETE FROM recipe`` haette 1532 Zeilen
Nutzerbestand **und** den ganzen Katalog genommen. Der Unterschied steht in
einem einzigen Wort der Bedingung.

Die Reihenfolge ist nicht frei: kein Fremdschluessel dieses Dienstes traegt
``ondelete``, und ``PRAGMA foreign_keys=ON`` steht in ``db.py``. Kinder zuerst,
sonst scheitert der Lauf an der Datenbank statt eine Aussage zu machen.

Das Scoping aus ``app/tenant.py`` greift hier nicht: es haengt an
``do_orm_execute`` und prueft ``is_select``. Ein rohes ``DELETE`` laeuft daran
vorbei, deshalb steht die Mandantenbedingung in jedem Schritt ausdruecklich.
"""

from __future__ import annotations

from app import konto_mechanik as mechanik

PLAN = mechanik.Plan(
    dienst="mealprep",
    schritte=(
        # Kinder zuerst, von innen nach aussen.
        mechanik.eigene("intake_item", warum="erfasste Mahlzeiten je Slot"),
        mechanik.eigene("meal_slot", warum="Essensplanung"),
        mechanik.eigene("shopping_list_line", warum="Zeilen der Einkaufslisten"),
        mechanik.eigene("shopping_list", warum="Einkaufslisten"),
        mechanik.eigene("shopping_rule", warum="Einkaufsregeln"),
        mechanik.eigene("supplement_log", warum="Einnahmeprotokoll"),
        mechanik.eigene("supplement", warum="Praeparate"),
        mechanik.eigene("recipe_hidden", warum="ausgeblendete Rezepte"),
        # Vor `recipe`, weil die Zutatenzeilen daran haengen.
        mechanik.eigene("recipe_ingredient",
                        warum="Zutaten EIGENER Rezepte (Katalog hat owner_sub NULL)"),
        mechanik.eigene("recipe",
                        warum="EIGENE Rezepte (Seed-Katalog hat owner_sub NULL, bleibt)"),
        mechanik.eigene("body_metric", warum="Koerperwerte"),
        mechanik.eigene("goal_phase", warum="Zielphasen"),
        mechanik.eigene("user_profile", warum="Profil"),
    ),
    # Der Zutaten-Stamm gehoert allen und niemandem: er traegt keine
    # Mandantenspalte und ist Nachschlagewerk, nicht Nutzerbestand.
    gemeinsam=frozenset({"ingredient"}),
)


if __name__ == "__main__":
    from app import models  # noqa: F401  (fuellt Base.metadata, sonst laufen die Pruefungen blind)
    from app.db import Base, SessionLocal

    raise SystemExit(mechanik.als_programm(PLAN, Base.metadata, SessionLocal))
