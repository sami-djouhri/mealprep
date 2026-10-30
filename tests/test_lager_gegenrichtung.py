"""Produkte im Lager, zu denen es hier keine Zutat gibt.

Der Befund, der dazu gefuehrt hat (gemessen 2026-10-24): **6 von 20
Lager-Produkten** mit echtem Bestand waren fuer mealprep unsichtbar, darunter
die Grundzutaten Mehl, Salz, Zucker und Karotten. Sie standen in keiner Liste
und in keiner Zahl.

Der Grund war nicht ein Fehler in der Pruefung, sondern ihre Richtung:
``vorschlaege()`` laeuft ueber die **unverknuepften Zutaten** und sucht je
Zutat ein Produkt. Ein Produkt, zu dem es hier ueberhaupt keine Zutat gibt,
kann diese Schleife nicht erreichen, weil es keinen Durchlauf gibt, der es
findet. Die Antwort meldete deshalb "1 Vorschlag, 33 unverknuepft" und sah
dabei wie eine vollstaendige Auskunft aus.

Beide Richtungen zusammen sind die ganze Frage: "Zutat da, Verknuepfung
fehlt" **und** "Zutat fehlt ganz". Die Tests hier decken die zweite.
"""

import pytest

from app.domain import DomainError
from app.models import Ingredient
from app.services import lager_abgleich
from app.services.lager_adapter import LagerAdapter, LagerUnavailable


class LagerMitBestand(LagerAdapter):
    """Attrappe mit Produktliste UND Bestand.

    Der Bestand gehoert dazu, weil er die Dringlichkeit traegt: ein Produkt
    ohne Zutat und ohne Vorrat kostet nur eine Planungsmoeglichkeit, eines mit
    Vorrat laesst nachkaufen, was im Haus liegt.
    """

    def __init__(self, produkte, bestand=None):
        super().__init__(base_url="http://mock-lager", timeout=1)
        self._produkte = produkte
        self._bestand = bestand

    def search_products(self, q=None, category=None, limit: int = 500):
        return self._produkte

    def bestand_gesamt(self):
        return self._bestand


def _zutat(db, name, unit="g", lager_product_id=None, synonyms=None):
    z = Ingredient(
        name_canonical=name,
        category="Test",
        default_unit=unit,
        shelf_life_type="MHD",
        lager_product_id=lager_product_id,
    )
    if synonyms:
        z.synonyms = synonyms
    db.add(z)
    db.commit()
    return z


# --- Die Gegenrichtung findet, was die Vorwaertsrichtung nicht erreicht ---

def test_produkt_ohne_zutat_wird_gefunden(db):
    """Der Kernfall: Mehl liegt im Lager, hier gibt es keine Zutat dafuer."""
    lager = LagerMitBestand(
        [{"id": 12, "name": "Mehl", "default_unit": "g", "category": "Backen"}],
        bestand={(12, "g"): 1000.0},
    )

    fehlend = lager_abgleich.produkte_ohne_zutat(db, lager)

    assert len(fehlend) == 1
    assert fehlend[0].lager_product_id == 12
    assert fehlend[0].lager_product_name == "Mehl"
    assert fehlend[0].kategorie == "Backen"
    assert fehlend[0].bestand == 1000.0


def test_genau_dieser_fall_bleibt_fuer_die_vorwaertsrichtung_unsichtbar(db):
    """Der eigentliche Beweis, und er gehoert in denselben Test.

    Dasselbe Lager, dieselbe leere Zutatenliste: ``vorschlaege()`` meldet
    null, ``produkte_ohne_zutat()`` meldet den Fund. Ohne die zweite Richtung
    ist die Auskunft "nichts zu tun" - und das ist die Lage, die vom
    2026-09-12 bis zum 2026-10-24 bestand.
    """
    lager = LagerMitBestand(
        [{"id": 12, "name": "Mehl", "default_unit": "g"}],
        bestand={(12, "g"): 1000.0},
    )

    assert lager_abgleich.vorschlaege(db, lager) == []
    assert len(lager_abgleich.produkte_ohne_zutat(db, lager)) == 1


def test_verknuepftes_produkt_fehlt_nicht(db):
    _zutat(db, "Mehl", lager_product_id=12)
    lager = LagerMitBestand([{"id": 12, "name": "Mehl", "default_unit": "g"}])

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []


# --- Der Schnitt zwischen den beiden Listen ---

def test_namensgleiche_zutat_zaehlt_nicht_als_fehlend(db):
    """Sonst stuende dasselbe Ding in beiden Listen.

    Die Zutat ist da und nur unverknuepft: das ist ein Vorschlagsfall. Zwei
    Listen, die dasselbe Produkt verschieden benennen, sind schlechter als
    eine.
    """
    _zutat(db, "Haferflocken")
    lager = LagerMitBestand([{"id": 20, "name": "Haferflocken", "default_unit": "g"}])

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []
    assert len(lager_abgleich.vorschlaege(db, lager)) == 1


def test_einheitenkonflikt_bleibt_vorschlag_und_wird_nicht_fehlend(db):
    """Paprika: Zutat in Stueck, Produkt in Gramm.

    Gemessen am 2026-10-24 der einzige Fall dieser Art im Bestand. Er
    braucht eine Einheiten-Entscheidung, keine neue Zutat. Stuende er hier,
    wuerde die Uebernahme eine zweite Paprika anlegen.
    """
    _zutat(db, "Paprika", unit="piece")
    lager = LagerMitBestand(
        [{"id": 15, "name": "Paprika", "default_unit": "g"}],
        bestand={(15, "g"): 200.0},
    )

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []
    assert lager_abgleich.vorschlaege(db, lager)[0].einheit_gleich is False


def test_synonym_der_zutat_deckt_das_produkt_ab(db):
    _zutat(db, "Magerquark", synonyms=["Quark"])
    lager = LagerMitBestand([{"id": 30, "name": "Quark", "default_unit": "g"}])

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []


def test_synonym_des_produkts_deckt_die_zutat_ab(db):
    """Die Gegenprobe zum vorigen Test: das Synonym steht drueben."""
    _zutat(db, "Magerquark")
    lager = LagerMitBestand([
        {"id": 30, "name": "Quark", "default_unit": "g", "synonyms": ["Magerquark"]},
    ])

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []


def test_umlaute_trennen_nicht(db):
    """Dieselbe Umschrift wie in der Vorwaertsrichtung, sonst driften beide."""
    _zutat(db, "Käse")
    lager = LagerMitBestand([{"id": 18, "name": "Kaese", "default_unit": "g"}])

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []


# --- Bestand: nicht gemessen ist nicht leer ---

def test_unbekannter_bestand_bleibt_none(db):
    """``None`` heisst nicht gemessen, ``0.0`` heisst gemessen und leer.

    Derselbe Unterschied, den ``bestand_gesamt`` traegt. Wer einen Ausfall
    als leeren Vorrat liest, haelt ein volles Regal fuer unwichtig.
    """
    lager = LagerMitBestand(
        [{"id": 12, "name": "Mehl", "default_unit": "g"}], bestand=None,
    )

    assert lager_abgleich.produkte_ohne_zutat(db, lager)[0].bestand is None


def test_gemessener_leerstand_ist_null_nicht_none(db):
    lager = LagerMitBestand(
        [{"id": 12, "name": "Mehl", "default_unit": "g"}], bestand={},
    )

    assert lager_abgleich.produkte_ohne_zutat(db, lager)[0].bestand == 0.0


def test_bestand_steht_oben(db):
    """Was im Vorrat liegt, ist der Grund, aus dem die Liste gelesen wird."""
    lager = LagerMitBestand(
        [
            {"id": 14, "name": "Salz", "default_unit": "g"},
            {"id": 12, "name": "Mehl", "default_unit": "g"},
        ],
        bestand={(12, "g"): 1000.0},
    )

    fehlend = lager_abgleich.produkte_ohne_zutat(db, lager)
    assert [p.lager_product_name for p in fehlend] == ["Mehl", "Salz"]


def test_lager_ohne_produkte_ergibt_nichts(db):
    assert lager_abgleich.produkte_ohne_zutat(db, LagerMitBestand([])) == []


# --- Uebernahme: eine Lager-Sorte wird hier zur Zutat ---

def test_uebernahme_legt_zutat_an_und_verknuepft(db):
    """Uebernommen wird, was drueben steht. Nichts wird geraten."""
    lager = LagerMitBestand([{
        "id": 12,
        "name": "Mehl",
        "default_unit": "g",
        "category": "Backen",
        "shelf_life_type": "MHD",
        "nutrition_per_100": {"kcal": 348.0, "protein_g": 10.0},
        "typical_pack_sizes": [1000],
        "synonyms": ["Weizenmehl"],
    }])

    zutat = lager_abgleich.zutat_aus_produkt(db, 12, lager)
    db.commit()

    assert zutat.name_canonical == "Mehl"
    assert zutat.lager_product_id == 12
    assert zutat.category == "Backen"
    assert zutat.default_unit == "g"
    assert zutat.nutrition_per_100["kcal"] == 348.0
    assert zutat.typical_pack_sizes == [1000]
    assert zutat.synonyms == ["Weizenmehl"]


def test_uebernahme_erfindet_keine_allergene(db):
    """⚠️ Allergene bleiben leer, weil das Lager sie nicht fuehrt.

    Bei einem Gesundheitsmerkmal ist ein erfundener Wert die schlechteste
    Wahl: leer heisst "unbekannt" und ist als solches lesbar, eine erfundene
    Liste liest sich als geprueft.
    """
    lager = LagerMitBestand([{"id": 18, "name": "Kaese", "default_unit": "g"}])

    zutat = lager_abgleich.zutat_aus_produkt(db, 18, lager)
    db.commit()

    assert zutat.allergens == []


def test_uebernahme_danach_ist_das_produkt_nicht_mehr_fehlend(db):
    """Der Kreis: was uebernommen ist, steht nicht mehr auf der Liste."""
    lager = LagerMitBestand(
        [{"id": 12, "name": "Mehl", "default_unit": "g"}],
        bestand={(12, "g"): 1000.0},
    )
    assert len(lager_abgleich.produkte_ohne_zutat(db, lager)) == 1

    lager_abgleich.zutat_aus_produkt(db, 12, lager)
    db.commit()

    assert lager_abgleich.produkte_ohne_zutat(db, lager) == []


def test_uebernahme_eines_unbekannten_produkts_scheitert(db):
    """Eine Nummer ins Leere wuerde eine Zutat mit Bestand 0 erzeugen."""
    lager = LagerMitBestand([{"id": 12, "name": "Mehl", "default_unit": "g"}])

    with pytest.raises(DomainError):
        lager_abgleich.zutat_aus_produkt(db, 4711, lager)


def test_schon_verknuepftes_produkt_wird_abgewiesen(db):
    """Sonst entstehen zwei Zutaten auf demselben Vorrat."""
    _zutat(db, "Mehl", lager_product_id=12)
    lager = LagerMitBestand([{"id": 12, "name": "Mehl", "default_unit": "g"}])

    with pytest.raises(DomainError):
        lager_abgleich.zutat_aus_produkt(db, 12, lager)


def test_namensgleiche_zutat_wird_zum_verknuepfen_verwiesen(db):
    """Zwei falsche Wege hierher, zwei verschiedene Auswege.

    Traegt eine Zutat den Namen schon, ist das ein Verknuepfungsfall fuer
    ``uebernehmen()``. Ein gemeinsames "geht nicht" wuerde beide Faelle in
    dieselbe Sackgasse schicken, und genau daran ist das Abhaken im Einkauf
    gescheitert.
    """
    _zutat(db, "Mehl")
    lager = LagerMitBestand([{"id": 12, "name": "Mehl", "default_unit": "g"}])

    with pytest.raises(DomainError) as fehler:
        lager_abgleich.zutat_aus_produkt(db, 12, lager)
    assert "verknuepft" in str(fehler.value).lower()


def test_uebernahme_bricht_ab_wenn_lager_schweigt(db):
    """Lieber keine Zutat als eine ungeprueft angelegte."""
    lager = LagerMitBestand([])

    with pytest.raises(LagerUnavailable):
        lager_abgleich.zutat_aus_produkt(db, 12, lager)
    db.rollback()
    assert db.query(Ingredient).count() == 0
