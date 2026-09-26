"""Zutaten mit Lager-Produkten verknuepfen.

★ Der Befund, der dazu gefuehrt hat (gemessen 2026-09-12): **null von 47
Zutaten** waren mit einem Lager-Produkt verknuepft, bei 45 Rezepten und 679
geplanten Mahlzeiten. ``Ingredient.lager_product_id`` ist die einzige
Verbindung zwischen beiden Diensten; ohne sie liefert ``get_available`` fuer
jede Zutat 0. Folge an jeder Stelle, an der der Adapter haengt: die
Machbarkeit eines Rezepts ist immer "nichts da", und die Einkaufsliste zieht
den Vorrat nie ab. Man kauft, was man schon hat.

Die Kopplung war also vollstaendig gebaut und trug nichts, weil eine
Verknuepfung fehlte, die man Zutat fuer Zutat von Hand haette setzen muessen.
"""

import pytest

from app.models import Ingredient
from app.services import lager_abgleich
from app.services.lager_adapter import LagerAdapter


class LagerMitProdukten(LagerAdapter):
    """Adapter-Attrappe, die eine Produktliste zurueckgibt."""

    def __init__(self, produkte):
        super().__init__(base_url="http://mock-lager", timeout=1)
        self._produkte = produkte

    def search_products(self, q=None, category=None, limit: int = 500):
        return self._produkte


def _zutat(db, name, unit="g", lager_product_id=None):
    z = Ingredient(
        name_canonical=name,
        category="Test",
        default_unit=unit,
        shelf_life_type="MHD",
        lager_product_id=lager_product_id,
    )
    db.add(z)
    db.commit()
    return z


# --- Normalisierung ---

def test_umlaute_werden_umgeschrieben():
    """★ Die beiden Dienste schreiben Umlaute unterschiedlich.

    Lager fuehrt "Kaese" und "Haehnchenbrust", andere Bestaende schreiben
    "Käse". Ohne Umschrift findet der Abgleich je nach Datenbestand die
    Haelfte nicht.
    """
    assert lager_abgleich.normalisieren("Käse") == lager_abgleich.normalisieren("Kaese")
    assert lager_abgleich.normalisieren("Hähnchenbrust") == lager_abgleich.normalisieren("Haehnchenbrust")
    assert lager_abgleich.normalisieren("Müsli") == "muesli"


def test_klammerzusatz_faellt_weg():
    assert lager_abgleich.normalisieren("Milch (1.5%)") == "milch"
    assert lager_abgleich.normalisieren("Kaese (gerieben)") == "kaese"


def test_verschiedene_namen_bleiben_verschieden():
    assert lager_abgleich.normalisieren("Reis") != lager_abgleich.normalisieren("Reibekaese")


# --- Vorschlaege ---

def test_namensgleiche_zutat_wird_vorgeschlagen(db):
    _zutat(db, "Haferflocken")
    lager = LagerMitProdukten([{"id": 20, "name": "Haferflocken", "default_unit": "g"}])

    v = lager_abgleich.vorschlaege(db, lager)
    assert len(v) == 1
    assert v[0].lager_product_id == 20
    assert v[0].treffer_art == "name"
    assert v[0].einheit_gleich is True
    assert v[0].hinweis is None


def test_klammerzusatz_trifft_trotzdem(db):
    _zutat(db, "Milch (1.5%)", unit="ml")
    lager = LagerMitProdukten([{"id": 4, "name": "Milch", "default_unit": "ml"}])
    assert lager_abgleich.vorschlaege(db, lager)[0].lager_product_id == 4


def test_synonym_trifft(db):
    _zutat(db, "Magerquark")
    lager = LagerMitProdukten([
        {"id": 30, "name": "Quark", "default_unit": "g", "synonyms": ["Magerquark"]},
    ])
    v = lager_abgleich.vorschlaege(db, lager)
    assert v[0].lager_product_id == 30
    assert v[0].treffer_art == "synonym"


def test_einheitenkonflikt_wird_gemeldet_nicht_verschwiegen(db):
    """★ Gemessen: Paprika steht hier in Stueck, im Lager in Gramm.

    Ein automatischer Abgleich wuerde 3 Stueck gegen 3 Gramm rechnen und
    Paprika von der Einkaufsliste streichen.
    """
    _zutat(db, "Paprika", unit="piece")
    lager = LagerMitProdukten([{"id": 15, "name": "Paprika", "default_unit": "g"}])

    v = lager_abgleich.vorschlaege(db, lager)[0]
    assert v.einheit_gleich is False
    assert "Einheiten unterschiedlich" in v.hinweis
    assert "piece" in v.hinweis and "g" in v.hinweis


def test_konflikte_stehen_oben(db):
    _zutat(db, "Haferflocken")
    _zutat(db, "Paprika", unit="piece")
    lager = LagerMitProdukten([
        {"id": 20, "name": "Haferflocken", "default_unit": "g"},
        {"id": 15, "name": "Paprika", "default_unit": "g"},
    ])
    v = lager_abgleich.vorschlaege(db, lager)
    assert v[0].ingredient_name == "Paprika", "was Aufmerksamkeit braucht, steht oben"


def test_ohne_gegenstueck_kein_vorschlag(db):
    _zutat(db, "Skyr")
    lager = LagerMitProdukten([{"id": 20, "name": "Haferflocken", "default_unit": "g"}])
    assert lager_abgleich.vorschlaege(db, lager) == []


def test_bereits_verknuepfte_zutat_wird_uebergangen(db):
    _zutat(db, "Haferflocken", lager_product_id=99)
    lager = LagerMitProdukten([{"id": 20, "name": "Haferflocken", "default_unit": "g"}])
    assert lager_abgleich.vorschlaege(db, lager) == []


def test_lager_ohne_produkte_ergibt_nichts(db):
    _zutat(db, "Haferflocken")
    assert lager_abgleich.vorschlaege(db, LagerMitProdukten([])) == []


# --- Uebernahme ---

def test_uebernahme_setzt_die_verknuepfung(db):
    z = _zutat(db, "Haferflocken")
    geaendert = lager_abgleich.uebernehmen(db, [(z.id, 20)])
    db.commit()

    assert len(geaendert) == 1
    assert db.get(Ingredient, z.id).lager_product_id == 20


def test_uebernahme_ueberschreibt_bestehendes_nicht(db):
    """Eine vorhandene Zuordnung ist eine Entscheidung, kein Vorschlag."""
    z = _zutat(db, "Haferflocken", lager_product_id=99)
    geaendert = lager_abgleich.uebernehmen(db, [(z.id, 20)])
    db.commit()

    assert geaendert == []
    assert db.get(Ingredient, z.id).lager_product_id == 99


def test_unbekannte_zutat_bricht_die_uebernahme_nicht(db):
    z = _zutat(db, "Haferflocken")
    geaendert = lager_abgleich.uebernehmen(db, [(4242, 1), (z.id, 20)])
    db.commit()

    assert len(geaendert) == 1
    assert db.get(Ingredient, z.id).lager_product_id == 20


# --- Existenzpruefung beim Verknuepfen ---
#
# ★ Angelegt am 2026-09-13. Eine Verknuepfung auf eine Produktnummer, die es
# drueben nicht gibt, scheitert nirgends: `get_available` liefert dafuer 0,
# und 0 liest sich als "nichts da". Man kauft dann dauerhaft etwas nach, das
# im Vorrat liegt. Genau diese Sorte stiller Fehler hat die Kette monatelang
# getragen, ohne dass ein Dienst rot wurde.


class LagerOhneAntwort(LagerAdapter):
    """Angebunden, aber liefert keine Produkte (Ausfall, 429, leerer Katalog)."""

    def __init__(self):
        super().__init__(base_url="http://mock-lager", timeout=1)

    def search_products(self, q=None, category=None, limit: int = 500):
        return []


def test_uebernahme_prueft_dass_es_das_produkt_gibt(db):
    z = _zutat(db, "Haferflocken")
    lager = LagerMitProdukten([{"id": 20, "name": "Haferflocken"}])

    geaendert = lager_abgleich.uebernehmen(db, [(z.id, 4711)], lager)
    db.commit()

    assert geaendert == [], "eine Nummer ins Leere darf nicht verknuepft werden"
    assert db.get(Ingredient, z.id).lager_product_id is None


def test_uebernahme_laesst_bekannte_produkte_durch(db):
    z = _zutat(db, "Haferflocken")
    lager = LagerMitProdukten([{"id": 20, "name": "Haferflocken"}])

    geaendert = lager_abgleich.uebernehmen(db, [(z.id, 20)], lager)
    db.commit()

    assert len(geaendert) == 1
    assert db.get(Ingredient, z.id).lager_product_id == 20


def test_uebernahme_bricht_ab_wenn_lager_schweigt(db):
    """Lieber gar nichts verknuepfen als ungeprueft.

    Eine leere Rueckgabe waere hier zweideutig: "nichts passte" und "nicht
    geprueft" saehen gleich aus. Deshalb eine Ausnahme, aus der der Endpunkt
    eine 503 macht.
    """
    from app.services.lager_adapter import LagerUnavailable

    z = _zutat(db, "Haferflocken")
    with pytest.raises(LagerUnavailable):
        lager_abgleich.uebernehmen(db, [(z.id, 20)], LagerOhneAntwort())
    db.rollback()
    assert db.get(Ingredient, z.id).lager_product_id is None


def test_ohne_lager_anbindung_wird_nicht_geprueft(db):
    """Saganta muss ohne die Nachbardienste laufen.

    Ist lager gar nicht angebunden, gibt es nichts zu pruefen, und die
    Verknuepfung bleibt moeglich. Sonst waere eine abgeschaltete Kopplung
    dasselbe wie eine kaputte.
    """
    z = _zutat(db, "Haferflocken")
    geaendert = lager_abgleich.uebernehmen(db, [(z.id, 20)], LagerAdapter(base_url=""))
    db.commit()

    assert len(geaendert) == 1
    assert db.get(Ingredient, z.id).lager_product_id == 20


def test_leere_paarliste_fragt_lager_gar_nicht(db):
    """Kein Abruf ohne Anlass."""
    assert lager_abgleich.uebernehmen(db, [], LagerOhneAntwort()) == []
