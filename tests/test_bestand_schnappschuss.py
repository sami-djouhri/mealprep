"""Ein Aufruf statt einer je Zutat, und ein Ausfall ist kein Nullwert.

★★ Der Fund vom 2026-09-13, aufgetaucht erst im Live-Lauf:

``_generate_no_commit`` rief ``get_available`` **je Zutat**. Bei 47 Zutaten
plus Mindestbestands-Regeln plus Vorlauf waren das rund fuenfzig Anfragen in
wenigen Sekunden. lager deckelt bei 60 je Minute und Absender und schickt
darueber hinaus **429** zurueck. ``get_available`` macht aus jedem Fehler eine
0, also entstand die Einkaufsliste aus lauter Nullen: alles zu kaufen, nichts
vorhanden. Sie sah dabei vollkommen plausibel aus.

Zwei Dinge trafen zusammen, und beide allein waeren harmlos gewesen: eine
Schleife, die pro Element ruft, und eine Nachsicht, die einen Fehler in einen
Messwert verwandelt.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.models import Ingredient, MealSlot, Recipe, RecipeIngredient
from app.services.lager_adapter import LagerAdapter, LagerUnavailable
from app.services.shopping import ShoppingService


def _adapter_mit_zaehler(antwort, zaehler: dict) -> LagerAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        zaehler.setdefault(request.url.path, 0)
        zaehler[request.url.path] += 1
        return antwort(request)

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    adapter._client = lambda: httpx.Client(  # noqa: SLF001 - Testzugriff
        base_url=adapter.base_url, transport=transport
    )
    return adapter


def _bestand(eintraege):
    def antwort(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/stock":
            return httpx.Response(200, json={
                "items": eintraege, "total": len(eintraege), "offset": 0, "limit": 500,
            })
        if request.url.path == "/api/stock/available":
            pid = int(request.url.params["product_id"])
            einheit = request.url.params["unit"]
            summe = sum(
                e["quantity"] for e in eintraege
                if e["product_id"] == pid and e["unit"] == einheit
            )
            return httpx.Response(200, json={"product_id": pid, "unit": einheit, "total": summe})
        if request.url.path == "/api/shopping-list":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])
    return antwort


def _zutaten_mit_rezept(db, anzahl: int):
    rezept = Recipe(name="Grosses Gericht")
    db.add(rezept)
    db.flush()
    for i in range(anzahl):
        z = Ingredient(name_canonical=f"Zutat {i}", default_unit="g", lager_product_id=i + 1)
        db.add(z)
        db.flush()
        db.add(RecipeIngredient(
            recipe_id=rezept.id, ingredient_id=z.id, amount=100.0, unit="g",
        ))
    db.add(MealSlot(
        date=date.today(), slot_type="dinner",
        planned_recipe_id=rezept.id, status="planned",
    ))
    db.commit()
    return rezept


def test_schnappschuss_deckungsgleich_mit_dem_einzelabruf():
    """Der Schnappschuss muss dasselbe liefern, nicht etwas Aehnliches.

    ``/api/stock/available`` summiert ``quantity`` ueber Zeilen mit **genau**
    dieser Einheit und rechnet nichts um. Genau das tut ``bestand_gesamt``
    auch. Waere das nicht so, wuerde der Schnappschuss stillschweigend andere
    Zahlen liefern als der Einzelabruf.
    """
    eintraege = [
        {"id": 1, "product_id": 7, "quantity": 300.0, "unit": "g"},
        {"id": 2, "product_id": 7, "quantity": 200.0, "unit": "g"},
        {"id": 3, "product_id": 7, "quantity": 2.0, "unit": "piece"},
        {"id": 4, "product_id": 9, "quantity": 500.0, "unit": "ml"},
    ]
    zaehler: dict[str, int] = {}
    a = _adapter_mit_zaehler(_bestand(eintraege), zaehler)

    einzeln = {
        (7, "g"): a.get_available(7, "g"),
        (7, "piece"): a.get_available(7, "piece"),
        (9, "ml"): a.get_available(9, "ml"),
        (99, "g"): a.get_available(99, "g"),
    }
    assert a.schnappschuss_laden() is True
    aus_schnappschuss = {
        schluessel: a.get_available(*schluessel) for schluessel in einzeln
    }

    assert einzeln == aus_schnappschuss
    assert einzeln[(7, "g")] == 500.0


def test_ein_aufruf_statt_einer_je_zutat(db):
    """Genau das war die Ursache der 429-Welle."""
    _zutaten_mit_rezept(db, 40)
    zaehler: dict[str, int] = {}
    a = _adapter_mit_zaehler(_bestand([]), zaehler)
    svc = ShoppingService(db, a)

    svc.generate_for_window(date.today(), days_ahead=3)

    assert zaehler.get("/api/stock/available", 0) == 0, \
        "kein Einzelabruf mehr, solange ein Schnappschuss geladen ist"
    assert zaehler.get("/api/stock", 0) <= 2, \
        f"der Bestand darf einmal geholt werden, gezaehlt: {zaehler}"


def test_kein_schnappschuss_kein_liste(db):
    """★★ Keine Daten heisst nicht null.

    Eine Einkaufsliste aus unbekanntem Bestand ist schlechter als keine: sie
    sieht aus wie eine Auskunft. Genau so entstand am 2026-09-13 eine Liste
    aus lauter Nullen, ohne dass irgendwo etwas scheiterte.
    """
    _zutaten_mit_rezept(db, 3)

    def nur_fehler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Zu viele Anfragen."})

    zaehler: dict[str, int] = {}
    a = _adapter_mit_zaehler(nur_fehler, zaehler)
    svc = ShoppingService(db, a)

    with pytest.raises(LagerUnavailable):
        svc.generate_for_window(date.today(), days_ahead=3)


def test_alte_liste_bleibt_stehen_wenn_nicht_gemessen_werden_kann(db, mock_lager):
    """Eine veraltete Liste ist besser als eine erfundene.

    Sie ist wenigstens einmal aus echten Zahlen entstanden.
    """
    _zutaten_mit_rezept(db, 2)
    svc = ShoppingService(db, mock_lager)
    alt = svc.generate_for_window(date.today(), days_ahead=3)
    assert alt.status == "open"

    mock_lager.ausgefallen = True
    with pytest.raises(LagerUnavailable):
        svc.generate_for_window(date.today(), days_ahead=3)

    db.expire_all()
    assert svc.get_current().id == alt.id
    assert svc.get_current().status == "open"


def test_ohne_lager_wird_weiter_gearbeitet(db):
    """Ein nicht konfiguriertes Lager ist kein Ausfall.

    Ein Selbsthoster ohne lager soll eine Einkaufsliste bekommen, nur eben
    ohne Bestandsabzug.
    """
    _zutaten_mit_rezept(db, 2)
    svc = ShoppingService(db, LagerAdapter(base_url=""))

    sl = svc.generate_for_window(date.today(), days_ahead=3)

    assert len(list(sl.lines)) == 2


def test_wiederholtes_laden_holt_nicht_noch_einmal():
    """Mehrere Schleifen duerfen den Schnappschuss unabhaengig anstossen."""
    zaehler: dict[str, int] = {}
    a = _adapter_mit_zaehler(_bestand([]), zaehler)

    assert a.schnappschuss_laden() is True
    assert a.schnappschuss_laden() is True
    assert a.schnappschuss_laden() is True

    assert zaehler.get("/api/stock", 0) == 1
    assert a.hat_schnappschuss is True
    a.schnappschuss_verwerfen()
    assert a.hat_schnappschuss is False
