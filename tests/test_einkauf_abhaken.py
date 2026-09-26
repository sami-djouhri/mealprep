"""Der Kreis schliesst sich: Einkauf zurueck in den Bestand.

Bis zum 2026-09-13 buchte mealprep beim Kochen ab und **nie** wieder auf.
``shopping.py`` kannte kein Einkaufen, kein Auffuellen, keinen Kauf. Der
rechnerische Bestand lief damit gegen null, und das sah aus wie ein leerer
Vorrat statt wie eine fehlende Kopplung.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain import DomainError
from app.models import Ingredient, MealSlot, Recipe, RecipeIngredient, ShoppingList, ShoppingListLine
from app.services.shopping import REASON_LAGER, ShoppingService


def _zutat(db, name="Reis", einheit="g", lager_id=None):
    z = Ingredient(name_canonical=name, default_unit=einheit, lager_product_id=lager_id)
    db.add(z)
    db.flush()
    return z


def _liste_mit_zeile(db, zutat, menge=500.0, einheit="g", brutto=-1.0):
    sl = ShoppingList(status="open")
    db.add(sl)
    db.flush()
    zeile = ShoppingListLine(
        shopping_list_id=sl.id,
        ingredient_id=zutat.id,
        needed_amount=menge,
        # -1.0 als Vorgabe heisst "wie die Menge": in den meisten Tests war
        # zum Erzeugungszeitpunkt nichts im Lager, netto ist dann gleich roh.
        bedarf_brutto=menge if brutto == -1.0 else brutto,
        unit=einheit,
    )
    db.add(zeile)
    db.commit()
    return sl, zeile


def test_abhaken_bucht_in_den_bestand(db, mock_lager):
    zutat = _zutat(db, lager_id=7)
    sl, zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    svc = ShoppingService(db, mock_lager)

    svc.abhaken(zeile.id)

    assert mock_lager.get_available(7, "g") == 500.0
    assert zeile.gekauft_am is not None
    assert zeile.gekaufte_menge == 500.0
    assert zeile.lager_stock_entry_id == mock_lager.eingebucht[0]["id"]
    assert mock_lager.eingebucht[0]["lot_note"] == f"Einkaufsliste #{sl.id}"


def test_abhaken_nimmt_die_tatsaechlich_gekaufte_menge(db, mock_lager):
    """Man kauft Packungen, keine Gramm. Die Abweichung ist der Normalfall."""
    zutat = _zutat(db, lager_id=7)
    _sl, zeile = _liste_mit_zeile(db, zutat, menge=450.0)
    svc = ShoppingService(db, mock_lager)

    svc.abhaken(zeile.id, menge=1000.0)

    assert mock_lager.get_available(7, "g") == 1000.0
    assert zeile.gekaufte_menge == 1000.0


def test_ohne_verknuepfung_wird_nicht_abgehakt(db, mock_lager):
    """★ Ein Haken ohne Buchung saehe aus wie ein geschlossener Kreis.

    Das ist der Punkt, an dem der Abgleich-Rueckstand sichtbar wird: am
    2026-09-13 waren 0 von 47 Zutaten verknuepft.
    """
    zutat = _zutat(db, name="Paprika", lager_id=None)
    _sl, zeile = _liste_mit_zeile(db, zutat)
    svc = ShoppingService(db, mock_lager)

    with pytest.raises(DomainError) as fehler:
        svc.abhaken(zeile.id)

    assert "nicht mit einem Lager-Produkt verknuepft" in fehler.value.message
    assert fehler.value.details["ingredient_name"] == "Paprika"
    assert zeile.gekauft_am is None
    assert mock_lager.eingebucht == []


def test_zweimal_abhaken_bucht_nicht_doppelt(db, mock_lager):
    zutat = _zutat(db, lager_id=7)
    _sl, zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    svc = ShoppingService(db, mock_lager)
    svc.abhaken(zeile.id)

    with pytest.raises(DomainError):
        svc.abhaken(zeile.id)

    assert mock_lager.get_available(7, "g") == 500.0


def test_haken_zuruecknehmen_entfernt_genau_den_eintrag(db, mock_lager):
    """Zurueckgenommen wird der gemerkte Eintrag, nicht ein aehnlicher.

    Deshalb steht ``lager_stock_entry_id`` an der Zeile: bei zwei Buchungen
    desselben Produkts ist sonst nicht entscheidbar, welche gemeint war.
    """
    zutat = _zutat(db, lager_id=7)
    _sl, zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    svc = ShoppingService(db, mock_lager)
    svc.abhaken(zeile.id)
    # Eine zweite, fremde Buchung desselben Produkts.
    mock_lager.einbuchen(product_id=7, menge=300.0, unit="g")
    assert mock_lager.get_available(7, "g") == 800.0

    svc.haken_zuruecknehmen(zeile.id)

    assert mock_lager.get_available(7, "g") == 300.0, "die fremde Buchung bleibt"
    assert zeile.gekauft_am is None
    assert zeile.lager_stock_entry_id is None


def test_lager_ausfall_setzt_keinen_haken(db, mock_lager):
    zutat = _zutat(db, lager_id=7)
    _sl, zeile = _liste_mit_zeile(db, zutat)
    svc = ShoppingService(db, mock_lager)
    mock_lager.ausgefallen = True

    from app.services.lager_adapter import LagerUnavailable

    with pytest.raises(LagerUnavailable):
        svc.abhaken(zeile.id)

    db.expire_all()
    assert db.get(ShoppingListLine, zeile.id).gekauft_am is None


# ---------------------------------------------------------------------------
# Restbedarf: live nachrechnen statt Momentaufnahme
# ---------------------------------------------------------------------------


def test_restbedarf_faellt_wenn_von_hand_eingebucht_wurde(db, mock_lager):
    """★ Der gespeicherte Wert ist eine Momentaufnahme vom Erzeugungszeitpunkt.

    Wer danach von Hand in lager einbucht, sah die Liste unveraendert und
    kaufte, was schon da war. Nachrechnen beim Abruf kann kein Ereignis
    verpassen, weil es keines braucht.
    """
    zutat = _zutat(db, lager_id=7)
    sl, _zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    svc = ShoppingService(db, mock_lager)

    assert svc.zeilen_mit_restbedarf(sl)[0]["noch_noetig"] == 500.0

    mock_lager.set_stock(7, "g", 200.0)
    zeile = svc.zeilen_mit_restbedarf(sl)[0]
    assert zeile["geplant"] == 500.0, "die Absicht bleibt stehen"
    assert zeile["noch_noetig"] == 300.0


def test_restbedarf_null_wenn_genug_da_ist(db, mock_lager):
    zutat = _zutat(db, lager_id=7)
    sl, _zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    mock_lager.set_stock(7, "g", 900.0)
    svc = ShoppingService(db, mock_lager)

    assert svc.zeilen_mit_restbedarf(sl)[0]["noch_noetig"] == 0.0


def test_lager_ausfall_ist_nicht_null(db, mock_lager):
    """★★ Keine Daten heisst nicht null.

    Wer einen Ausfall als leeren Vorrat liest, zeigt die volle geplante Menge
    und laesst das wie eine Messung aussehen. Hier wird die Unsicherheit
    benannt und das Abhaken gesperrt.
    """
    zutat = _zutat(db, lager_id=7)
    sl, _zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    mock_lager.set_stock(7, "g", 900.0)
    mock_lager.ausgefallen = True
    svc = ShoppingService(db, mock_lager)

    zeile = svc.zeilen_mit_restbedarf(sl)[0]
    assert zeile["bestand_unbekannt"] is True
    assert zeile["noch_noetig"] == 500.0


def test_abgehakte_zeile_braucht_nichts_mehr(db, mock_lager):
    zutat = _zutat(db, lager_id=7)
    sl, zeile = _liste_mit_zeile(db, zutat, menge=500.0)
    svc = ShoppingService(db, mock_lager)
    svc.abhaken(zeile.id)

    z = svc.zeilen_mit_restbedarf(sl)[0]
    assert z["noch_noetig"] == 0.0
    assert z["gekaufte_menge"] == 500.0


def test_der_vorrat_wird_nur_einmal_abgezogen(db, mock_lager):
    """★★ Der Fehler, den erst der Live-Lauf zeigte.

    ``needed_amount`` ist bereits Bedarf minus Bestand. Wer das beim Anzeigen
    noch einmal gegen den Bestand haelt, zieht denselben Vorrat zweimal ab.
    Live gemessen am 2026-09-13: elf von dreiundzwanzig Zeilen standen danach
    auf "0 noch noetig", obwohl sie auf der Liste standen. Zwei Abzuege sehen
    aus wie ein gut gefuellter Vorrat.
    """
    zutat = _zutat(db, lager_id=7)
    # Bedarf 800, davon waren bei der Erzeugung 300 da, also 500 zu kaufen.
    sl, _zeile = _liste_mit_zeile(db, zutat, menge=500.0, brutto=800.0)
    mock_lager.set_stock(7, "g", 300.0)
    svc = ShoppingService(db, mock_lager)

    z = svc.zeilen_mit_restbedarf(sl)[0]
    assert z["noch_noetig"] == 500.0, "unveraenderter Bestand, unveraenderter Rest"

    mock_lager.set_stock(7, "g", 800.0)
    assert svc.zeilen_mit_restbedarf(sl)[0]["noch_noetig"] == 0.0

    mock_lager.set_stock(7, "g", 0.0)
    assert svc.zeilen_mit_restbedarf(sl)[0]["noch_noetig"] == 800.0, \
        "faellt der Vorrat, waechst der Bedarf ueber den urspruenglichen Rest"


def test_lager_vorschlag_wird_nicht_nachgerechnet(db, mock_lager):
    """★ ``bedarf_brutto is None`` heisst ausdruecklich: nicht nachrechnen.

    lagers Zahl entsteht aus Mindestbestand, Wochenverbrauch und
    Ablaufdatum. Gegen den Bestand gehalten ergaebe der Fall "laeuft bald ab"
    immer null: abgezogen wuerde genau der Vorrat, dessen Verlust der
    Vorschlag ersetzt.
    """
    zutat = _zutat(db, lager_id=7)
    sl, _zeile = _liste_mit_zeile(db, zutat, menge=300.0, brutto=None)
    mock_lager.set_stock(7, "g", 300.0)
    svc = ShoppingService(db, mock_lager)

    z = svc.zeilen_mit_restbedarf(sl)[0]
    assert z["noch_noetig"] == 300.0
    assert z["bedarf_brutto"] is None
    assert z["bestand_unbekannt"] is False


def test_mindestbestand_zieht_den_vorrat_nicht_doppelt_ab(db, mock_lager):
    """★ Vorbestehender Fehler, sichtbar erst mit verknuepften Zutaten.

    Stufe 2 legte ``target - avail`` ab, Stufe 3 zog ``avail`` erneut ab:
    ``target - 2*avail``. Je mehr man im Vorrat hatte, desto weiter unter dem
    Mindestbestand landete man nach dem Einkauf. Nie aufgefallen, weil bis
    zum 2026-09-13 keine Zutat verknuepft war und ``avail`` ueberall 0 gab.
    """
    from app.models import ShoppingRule

    zutat = _zutat(db, name="Reis", lager_id=7)
    db.add(ShoppingRule(
        ingredient_id=zutat.id, min_stock=1000.0, target_stock=1000.0, unit="g",
    ))
    db.commit()
    mock_lager.set_stock(7, "g", 400.0)
    svc = ShoppingService(db, mock_lager)

    sl = svc.generate_for_window(date.today(), days_ahead=3)

    zeile = next(z for z in sl.lines if z.ingredient_id == zutat.id)
    assert zeile.needed_amount == 600.0, "1000 Ziel minus 400 Vorrat, einmal"
    assert zeile.bedarf_brutto == 1000.0


def test_nicht_verknuepfte_zeile_ist_offen_und_nicht_unbekannt(db, mock_lager):
    """Ohne Verknuepfung gibt es keinen Bestand, gegen den man rechnen kann.

    Das ist ein offener Punkt (voller Betrag, ``verknuepft: False``), aber
    keine ausgefallene Messung.
    """
    zutat = _zutat(db, name="Paprika", lager_id=None)
    sl, _zeile = _liste_mit_zeile(db, zutat, menge=3.0, einheit="piece")
    svc = ShoppingService(db, mock_lager)

    z = svc.zeilen_mit_restbedarf(sl)[0]
    assert z["verknuepft"] is False
    assert z["bestand_unbekannt"] is False
    assert z["noch_noetig"] == 3.0


# ---------------------------------------------------------------------------
# Lagers Vorschlaege als vierte Quelle der Liste
# ---------------------------------------------------------------------------


def test_lager_vorschlag_kommt_auf_die_liste(db, mock_lager):
    """lager sieht Bedarf, den kein geplantes Gericht anfordert."""
    zutat = _zutat(db, name="Mehl", lager_id=12)
    mock_lager.set_suggestions([{
        "product_id": 12,
        "product_name": "Mehl",
        "suggested_quantity": 1000.0,
        "unit": "g",
        "reason": "low_stock",
        "current_stock": 0.0,
    }])
    svc = ShoppingService(db, mock_lager)

    sl = svc.generate_for_window(date.today(), days_ahead=3)

    zeilen = [z for z in sl.lines if z.ingredient_id == zutat.id]
    assert len(zeilen) == 1
    assert zeilen[0].reason_codes == [REASON_LAGER]
    assert zeilen[0].needed_amount == 1000.0


def test_lager_vorschlag_verdraengt_keinen_plan_bedarf(db, mock_lager):
    """Steht die Zutat schon wegen eines Rezepts drauf, bleibt es dabei."""
    zutat = _zutat(db, name="Reis", lager_id=7)
    rezept = Recipe(name="Reispfanne")
    db.add(rezept)
    db.flush()
    db.add(RecipeIngredient(
        recipe_id=rezept.id, ingredient_id=zutat.id, amount=250.0, unit="g",
    ))
    db.add(MealSlot(
        date=date.today(), slot_type="dinner", planned_recipe_id=rezept.id, status="planned",
    ))
    db.commit()

    mock_lager.set_suggestions([{
        "product_id": 7, "product_name": "Reis", "suggested_quantity": 9999.0,
        "unit": "g", "reason": "weekly_average", "current_stock": 0.0,
    }])
    svc = ShoppingService(db, mock_lager)

    sl = svc.generate_for_window(date.today(), days_ahead=3)

    zeilen = [z for z in sl.lines if z.ingredient_id == zutat.id]
    assert len(zeilen) == 1, "keine zweite Zeile fuer dieselbe Zutat"
    assert "MISSING_FOR_PLAN" in zeilen[0].reason_codes
    assert zeilen[0].needed_amount == 250.0


def test_unverknuepfter_vorschlag_wird_nicht_erfunden(db, mock_lager):
    """Ein Lager-Produkt ohne passende Zutat erzeugt hier keine Zeile."""
    _zutat(db, name="Reis", lager_id=7)
    mock_lager.set_suggestions([{
        "product_id": 999, "product_name": "Kaffeefilter",
        "suggested_quantity": 100.0, "unit": "piece",
        "reason": "low_stock", "current_stock": 0.0,
    }])
    svc = ShoppingService(db, mock_lager)

    sl = svc.generate_for_window(date.today(), days_ahead=3)

    assert list(sl.lines) == []
