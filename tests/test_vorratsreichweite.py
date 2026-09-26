"""Vorratsreichweite: ein Abruf statt einem je Zutat, und 0 ist nicht unbekannt.

Zwei Dinge werden hier festgehalten, beide aus dem Lauf vom 2026-09-13:

1. ★★ **Die Schleife.** ``calculate_days_of_food`` rief je verknuepfter Zutat
   einmal ``get_available`` und einmal ``get_turnover``. Gemessen kostete ein
   Dashboard-Aufruf 17 Anfragen an lager bei einem Deckel von 60 je Minute.
   Was danach kam, war nicht langsamer, sondern falsch: der Adapter macht aus
   einem 429 eine Null.

2. ★★ **Die Null.** Vier verschiedene Lagen gaben dieselbe ``0`` zurueck:
   lager nicht angebunden, nichts verknuepft, lager nicht erreichbar, keine
   Verbrauchsdaten. Nur die letzte hat mit dem Vorrat zu tun, und keine
   bedeutet "das Essen ist alle". Das Dashboard zeichnete trotzdem einen roten
   Balken mit "~0.0 Tage".
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app.models import Ingredient, Recipe, RecipeIngredient
from app.schemas import DaysOfFoodResult
from app.services.lager_adapter import LagerAdapter
from app.services.stock_forecast import calculate_days_of_food
from tests.conftest import MockLagerAdapter


@pytest.fixture
def verknuepfte_zutaten(db):
    """Zwei Zutaten, beide mit Lager-Bezug und beide in einem Rezept."""
    rezept = Recipe(name="Testgericht")
    db.add(rezept)
    db.flush()

    zutaten = []
    for i, (name, pid) in enumerate([("Reis", 11), ("Linsen", 12)]):
        zutat = Ingredient(name_canonical=name, default_unit="g", lager_product_id=pid)
        db.add(zutat)
        db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=rezept.id,
                ingredient_id=zutat.id,
                amount=100.0 + i,
                unit="g",
            )
        )
        zutaten.append(zutat)
    db.commit()
    return zutaten


# ---------------------------------------------------------------------------
# 1. Die Schleife
# ---------------------------------------------------------------------------


def test_ein_sammelabruf_statt_eines_je_zutat(db, verknuepfte_zutaten, monkeypatch):
    """Der Kern: die Zahl der Anfragen darf nicht mit den Zutaten wachsen.

    Gezaehlt wird auf HTTP-Ebene, nicht an der Attrappe: genau dort lag das
    Problem, und nur dort greift der Anfragedeckel von lager.
    """
    pfade: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pfade.append(request.url.path)
        if request.url.path == "/api/stock":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 1, "product_id": 11, "quantity": 900.0, "unit": "g"},
                        {"id": 2, "product_id": 12, "quantity": 400.0, "unit": "g"},
                    ],
                    "total": 2,
                    "offset": 0,
                    "limit": 500,
                },
            )
        if request.url.path == "/api/stats/turnover":
            return httpx.Response(
                200,
                json=[
                    {
                        "product_id": 11,
                        "product_name": "Reis",
                        "avg_daily": 90.0,
                        "unit": "g",
                        "days_analysed": 30,
                    },
                    {
                        "product_id": 12,
                        "product_name": "Linsen",
                        "avg_daily": 100.0,
                        "unit": "g",
                        "days_analysed": 30,
                    },
                ],
            )
        return httpx.Response(404, json={"error": "unerwartet"})

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    ergebnis = calculate_days_of_food(db, adapter)

    assert ergebnis.belastbar
    # Reis: 900/90 = 10 Tage, Linsen: 400/100 = 4 Tage. Der engste zaehlt.
    assert ergebnis.days == 4.0
    assert ergebnis.limiting_ingredient == "Linsen"

    assert pfade.count("/api/stats/turnover") == 1, (
        f"Turnover wurde {pfade.count('/api/stats/turnover')} mal geholt. "
        "Der Sammelabruf ist wieder eine Schleife geworden."
    )
    assert not any(p.startswith("/api/stats/turnover/") for p in pfade), (
        "Der Einzelabruf je Produkt darf hier nicht mehr vorkommen."
    )
    assert len(pfade) <= 2, f"Erwartet zwei Abrufe, gemessen: {pfade}"


def test_zahl_der_abrufe_bleibt_gleich_bei_mehr_zutaten(db, monkeypatch):
    """Zwanzig Zutaten duerfen nicht zwanzig Abrufe kosten.

    Der alte Weg waere hier bei 40 Anfragen gelandet, also deutlich ueber dem
    Deckel von 60 je Minute, sobald das Dashboard zweimal geoeffnet wird.
    """
    rezept = Recipe(name="Grosses Gericht")
    db.add(rezept)
    db.flush()
    for i in range(20):
        zutat = Ingredient(
            name_canonical=f"Zutat {i}", default_unit="g", lager_product_id=100 + i
        )
        db.add(zutat)
        db.flush()
        db.add(
            RecipeIngredient(
                recipe_id=rezept.id, ingredient_id=zutat.id, amount=50.0, unit="g"
            )
        )
    db.commit()

    pfade: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pfade.append(request.url.path)
        if request.url.path == "/api/stock":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": i, "product_id": 100 + i, "quantity": 500.0, "unit": "g"}
                        for i in range(20)
                    ],
                    "total": 20,
                    "offset": 0,
                    "limit": 500,
                },
            )
        if request.url.path == "/api/stats/turnover":
            return httpx.Response(
                200,
                json=[
                    {
                        "product_id": 100 + i,
                        "product_name": f"Zutat {i}",
                        "avg_daily": 25.0,
                        "unit": "g",
                        "days_analysed": 30,
                    }
                    for i in range(20)
                ],
            )
        return httpx.Response(404, json={"error": "unerwartet"})

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    ergebnis = calculate_days_of_food(db, adapter)

    assert ergebnis.belastbar
    assert len(pfade) <= 2, f"20 Zutaten kosteten {len(pfade)} Abrufe: {pfade}"


# ---------------------------------------------------------------------------
# 2. Die Null
# ---------------------------------------------------------------------------


def test_ausfall_ist_nicht_belastbar(db, verknuepfte_zutaten):
    """Lager antwortet nicht: keine Aussage ueber den Vorrat."""
    lager = MockLagerAdapter()
    lager.ausgefallen = True

    ergebnis = calculate_days_of_food(db, lager)

    assert ergebnis.belastbar is False
    assert ergebnis.grund
    assert "nicht geantwortet" in ergebnis.grund


def test_nichts_verknuepft_ist_nicht_belastbar(db):
    lager = MockLagerAdapter()
    ergebnis = calculate_days_of_food(db, lager)
    assert ergebnis.belastbar is False
    assert "verknuepft" in ergebnis.grund


def test_lager_nicht_angebunden_ist_nicht_belastbar(db, verknuepfte_zutaten):
    ergebnis = calculate_days_of_food(db, LagerAdapter(base_url=""))
    assert ergebnis.belastbar is False
    assert "nicht angebunden" in ergebnis.grund


def test_ohne_verbrauchsdaten_ist_nicht_belastbar(db, verknuepfte_zutaten):
    """Gemessen, aber keine Zutat hat Verbrauch: das sagt nichts ueber den Vorrat.

    Der Unterschied zum Ausfall steht im Grund, nicht in der Zahl. Beide geben
    ``days: 0``, und genau deshalb darf die Zahl nicht allein reisen.
    """
    lager = MockLagerAdapter()
    lager.set_stock(11, "g", 900.0)
    lager.set_stock(12, "g", 400.0)

    ergebnis = calculate_days_of_food(db, lager)

    assert ergebnis.belastbar is False
    assert "Verbrauchsdaten" in ergebnis.grund
    assert ergebnis.details, "die Einzelheiten je Zutat sollen erhalten bleiben"


def test_mit_daten_ist_belastbar(db, verknuepfte_zutaten):
    lager = MockLagerAdapter()
    lager.set_stock(11, "g", 900.0)
    lager.set_stock(12, "g", 400.0)
    lager.set_turnover(11, 90.0)
    lager.set_turnover(12, 100.0)

    ergebnis = calculate_days_of_food(db, lager)

    assert ergebnis.belastbar is True
    assert ergebnis.grund is None
    assert ergebnis.days == 4.0


def test_schema_erzwingt_einen_grund():
    """Eine unbelastbare Zahl ohne Begruendung ist fuer den Leser Schweigen."""
    with pytest.raises(ValidationError):
        DaysOfFoodResult(days=0, belastbar=False)


def test_schema_vorgabe_ist_fail_closed():
    """Wer ``belastbar`` vergisst, bekommt keine Zusicherung geschenkt."""
    with pytest.raises(ValidationError):
        DaysOfFoodResult(days=7.5)


# ---------------------------------------------------------------------------
# Der Adapter selbst
# ---------------------------------------------------------------------------


def test_verbrauchsraten_none_bei_ausfall(monkeypatch):
    """``None`` heisst nicht gemessen, ``{}`` heisst gemessen und leer."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Zu viele Anfragen."})

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    assert adapter.verbrauchsraten() is None
    assert adapter.raten_laden() is False


def test_verbrauchsraten_leer_ist_gemessen(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    assert adapter.verbrauchsraten() == {}
    assert adapter.raten_laden() is True


def test_altes_lager_ohne_sammelabruf(monkeypatch, caplog):
    """404 auf den Sammelabruf heisst: alte Fassung, nicht "keine Daten"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    with caplog.at_level("WARNING"):
        assert adapter.verbrauchsraten() is None
    assert any("Sammelabruf" in r.message or "turnover" in r.message for r in caplog.records)


def test_geladene_raten_ersparen_den_einzelabruf(monkeypatch):
    aufrufe: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request.url.path)
        return httpx.Response(
            200,
            json=[
                {
                    "product_id": 5,
                    "product_name": "Hafer",
                    "avg_daily": 50.0,
                    "unit": "g",
                    "days_analysed": 30,
                }
            ],
        )

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    assert adapter.raten_laden() is True
    assert adapter.get_turnover(5)["avg_daily"] == 50.0
    assert adapter.get_turnover(999) == {"avg_daily": 0, "unit": ""}
    assert len(aufrufe) == 1, f"Nach dem Laden darf kein HTTP mehr kommen: {aufrufe}"
