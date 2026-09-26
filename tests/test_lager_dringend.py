"""Was muss diese Woche weg: lagers Wissen, das mealprep nicht abholte.

``/api/critical`` und ``/api/stats/expiry-forecast`` lagen seit Langem
bereit und hatten in mealprep keinen einzigen Leser.
"""

from __future__ import annotations

from app.services import lager_dringend


def test_zusammengefuehrt_ueber_die_produktnummer(db, mock_lager):
    """Doppelt genannte Posten sind der Normalfall, nicht die Ausnahme."""
    mock_lager.set_critical([
        {"product_id": 1, "name": "Reis", "unit": "g", "quantity": 300.0,
         "days_left": -5, "reasons": ["abgelaufen"]},
    ])
    mock_lager.set_forecast([
        {"product_id": 1, "product_name": "Reis", "unit": "g",
         "quantity": 300.0, "days_left": 2, "reason": "expire"},
        {"product_id": 5, "product_name": "Joghurt", "unit": "g",
         "quantity": 500.0, "days_left": 3, "reason": "expire"},
    ])

    ergebnis = lager_dringend.was_muss_weg(mock_lager)

    assert ergebnis["erreichbar"] is True
    assert [p["product_id"] for p in ergebnis["posten"]] == [1, 5]
    reis = ergebnis["posten"][0]
    assert reis["tage_uebrig"] == -5, "die fruehere Faelligkeit gewinnt"
    assert "abgelaufen" in reis["gruende"]
    assert "expire" in reis["gruende"]
    assert reis["abgelaufen"] is True


def test_weit_entfernte_faelligkeit_gehoert_nicht_in_die_woche(db, mock_lager):
    mock_lager.set_forecast([
        {"product_id": 9, "product_name": "Mehl", "unit": "g",
         "quantity": 1000.0, "days_left": 40, "reason": "expire"},
    ])

    ergebnis = lager_dringend.was_muss_weg(mock_lager)

    assert ergebnis["posten"] == []


def test_frist_sortiert_das_draengendste_nach_oben(db, mock_lager):
    mock_lager.set_forecast([
        {"product_id": 2, "product_name": "Butter", "days_left": 4, "unit": "g"},
        {"product_id": 3, "product_name": "Milch", "days_left": -2, "unit": "ml"},
        {"product_id": 4, "product_name": "Eier", "days_left": 0, "unit": "piece"},
    ])

    posten = lager_dringend.was_muss_weg(mock_lager)["posten"]

    assert [p["name"] for p in posten] == ["Milch", "Eier", "Butter"]
    assert posten[0]["abgelaufen"] is True
    assert posten[1]["abgelaufen"] is False


def test_nicht_erreichbar_ist_nicht_leer(db, mock_lager):
    """★ Ein leerer Kasten sieht aus wie "nichts laeuft ab".

    Das ist die falsche Aussage, wenn niemand nachgesehen hat. Beide
    Adapter-Methoden geben bei Ausfall dieselbe leere Liste zurueck wie bei
    echtem Nichts, deshalb entscheidet ein zusaetzlicher billiger Abruf.
    """
    ergebnis = lager_dringend.was_muss_weg(mock_lager)

    assert ergebnis["erreichbar"] is False
    assert ergebnis["posten"] == []
    assert ergebnis["grund"]


def test_ohne_lager_konfiguration_wird_nichts_behauptet(db):
    from app.services.lager_adapter import LagerAdapter

    ergebnis = lager_dringend.was_muss_weg(LagerAdapter(base_url=""))

    assert ergebnis["erreichbar"] is False
    assert "nicht konfiguriert" in ergebnis["grund"]
