"""Die Einkaufsliste darf an ihrem eigenen Zustand nicht sterben.

GEFUNDEN AM 2026-09-06, live: `/shopping/current` und `/shopping/current/view`
lieferten 500 mit `MultipleResultsFound`. In der Datenbank standen zwei offene
Listen desselben Besitzers, und der Lesepfad benutzte `scalar_one_or_none()` -
eine Behauptung ueber die Daten, die die App selbst widerlegt hatte:
`generate_for_window()` erzeugte eine neue Liste, ohne die alte zu schliessen,
waehrend `auto_refresh()` es tat. Zweimal „erzeugen" genuegte, danach war die
Einkaufsliste weg, und zwar dauerhaft, bis jemand die Datenbank anfasst.

Zwei Tests, weil es zwei getrennte Fehler waren:
  * die schreibende Seite darf den Zustand gar nicht erst herstellen,
  * die lesende Seite darf an ihm nicht zerbrechen, falls er doch entsteht
    (aus einem Abbruch, einer Migration, einem alten Bestand).
Nur den zweiten zu haben hiesse, den Fehler zu verwalten statt ihn abzustellen;
nur den ersten zu haben laesst jeden Altbestand weiter 500 liefern.
"""

from datetime import date, timedelta

from app.models import Ingredient, MealSlot, Recipe, RecipeIngredient, ShoppingList
from app.services.shopping import ShoppingService

from tests.conftest import MockLagerAdapter  # noqa: F401  (Fixture-Import)


def _plane_eine_mahlzeit(db, tag):
    """Minimaler Plan, damit die Erzeugung ueberhaupt etwas zu tun hat."""
    zutat = Ingredient(name_canonical="Haehnchenbrust", default_unit="g")
    db.add(zutat)
    db.flush()
    rezept = Recipe(name="Testgericht", portions_default=1)
    db.add(rezept)
    db.flush()
    db.add(RecipeIngredient(recipe_id=rezept.id, ingredient_id=zutat.id, amount=200, unit="g"))
    db.add(MealSlot(date=tag, slot_type="dinner", status="planned", planned_recipe_id=rezept.id))
    db.flush()
    return zutat


def _offene(db):
    return db.query(ShoppingList).filter(ShoppingList.status == "open").all()


def test_zweimal_erzeugen_laesst_genau_eine_offene_liste(db, mock_lager):
    """Der Weg, auf dem der kaputte Zustand entstand: zweimal erzeugen.

    Vorher blieben zwei offene Listen stehen und die naechste Anzeige warf.
    """
    heute = date.today()
    _plane_eine_mahlzeit(db, heute)
    svc = ShoppingService(db, lager=mock_lager)

    erste = svc.generate_for_window(heute, days_ahead=1)
    zweite = svc.generate_for_window(heute, days_ahead=1)

    assert erste.id != zweite.id, "die zweite Erzeugung soll eine neue Liste anlegen"
    offen = _offene(db)
    assert len(offen) == 1, f"genau eine offene Liste erwartet, gefunden: {len(offen)}"
    assert offen[0].id == zweite.id, "offen bleiben soll die neu erzeugte"
    assert db.get(ShoppingList, erste.id).status == "closed", "die alte gehoert geschlossen"


def test_anzeige_ueberlebt_zwei_offene_listen(db, mock_lager):
    """Selbst wenn der Zustand doch entsteht, muss die Anzeige tragen.

    Genau hier warf `scalar_one_or_none()`. Erwartet wird die NEUESTE Liste,
    nicht irgendeine: die Sortierung entscheidet, was der Nutzer sieht.
    """
    heute = date.today()
    svc = ShoppingService(db, lager=mock_lager)

    alt = ShoppingList(status="open", created_at=heute - timedelta(days=2))
    neu = ShoppingList(status="open", created_at=heute)
    db.add_all([alt, neu])
    db.flush()

    aktuell = svc.get_current()

    assert aktuell is not None, "zwei offene Listen duerfen keine leere Antwort ergeben"
    assert aktuell.id == neu.id, "die neuere Liste gewinnt"


def test_ohne_liste_bleibt_es_bei_keiner(db, mock_lager):
    """Die Gegenprobe: `None` ist weiterhin eine gueltige Antwort, kein Fehler."""
    assert ShoppingService(db, lager=mock_lager).get_current() is None
