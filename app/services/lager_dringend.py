"""Was im Lager diese Woche weg muss.

★ Warum es das gibt: lager weiss mehr, als mealprep abgeholt hat.
``/api/critical`` und ``/api/stats/expiry-forecast`` liegen seit Langem
bereit und hatten in mealprep keinen einzigen Leser. Die Daten waren also
nicht das Fehlende, der Abruf war es.

Zwei Quellen, weil sie verschiedene Fragen beantworten:

- ``/api/critical`` ist die Bewertung des Lagers selbst (abgelaufen,
  MHD kritisch, leer) und bringt eine Reihenfolge mit.
- ``/api/stats/expiry-forecast`` sieht weiter nach vorn und nennt auch, was
  erst in einigen Tagen faellig wird.

Zusammengefuehrt wird ueber ``product_id``, die frueheste Faelligkeit
gewinnt. Doppelt genannte Posten waeren sonst der Normalfall, nicht die
Ausnahme.
"""

from __future__ import annotations

import logging

from app.services.lager_adapter import LagerAdapter

log = logging.getLogger(__name__)

#: Weiter nach vorn zu schauen bringt fuer einen Wochenplan nichts: was in
#: drei Wochen faellig wird, gehoert nicht in die Frage "was muss diese
#: Woche weg".
VORSCHAU_TAGE = 10


def _zahl(wert, vorgabe=None):
    try:
        return float(wert)
    except (TypeError, ValueError):
        return vorgabe


def _tage(eintrag: dict):
    """Verbleibende Tage aus dem ersten Feld, das es GIBT.

    ★ Hier stand ``eintrag.get("days_left") or eintrag.get("days_until_expiry")``,
    und das ist falsch fuer genau den draengendsten Fall: ``days_left`` ist
    **0**, wenn etwas heute ablaeuft, und 0 ist unwahr. Der Posten fiel damit
    auf das zweite Feld zurueck, fand dort nichts und landete als "ohne
    Datum" am Ende der Liste - also genau dort, wo man ihn uebersieht.
    Gefunden vom Sortier-Test, nicht im Betrieb.
    """
    for feld in ("days_left", "days_until_expiry"):
        if feld in eintrag and eintrag[feld] is not None:
            return _zahl(eintrag[feld])
    return None


def was_muss_weg(
    lager: LagerAdapter | None = None, vorschau_tage: int = VORSCHAU_TAGE
) -> dict:
    """Dringende Lager-Posten, zusammengefuehrt und sortiert.

    ⚠️ ``erreichbar: False`` ist nicht dasselbe wie eine leere Liste. Ein
    leerer Kasten sieht aus wie "nichts laeuft ab" und ist die falsche
    Aussage, wenn niemand nachgesehen hat.
    """
    lager = lager or LagerAdapter()
    if not lager.available:
        return {"erreichbar": False, "posten": [], "grund": "Lager nicht konfiguriert"}

    kritisch = lager.get_critical()
    vorhersage = lager.get_expiry_forecast()
    if not kritisch and not vorhersage:
        # ★ Beide leer heisst zweierlei: "nichts laeuft ab" oder "niemand hat
        # nachgesehen". Die Adapter-Methoden geben bei Ausfall dieselbe leere
        # Liste zurueck wie bei echtem Nichts. Ein einzelner billiger Abruf
        # entscheidet das, statt es offenzulassen.
        if not lager.search_products(limit=1):
            return {
                "erreichbar": False,
                "posten": [],
                "grund": "Lager antwortet nicht",
            }

    posten: dict[int, dict] = {}

    for eintrag in kritisch:
        pid = eintrag.get("product_id")
        if pid is None:
            continue
        posten[pid] = {
            "product_id": pid,
            "name": eintrag.get("name") or eintrag.get("product_name") or f"#{pid}",
            "menge": _zahl(eintrag.get("quantity")),
            "unit": eintrag.get("unit") or "",
            "tage_uebrig": _tage(eintrag),
            "gruende": list(eintrag.get("reasons") or []),
        }

    for eintrag in vorhersage:
        pid = eintrag.get("product_id")
        if pid is None:
            continue
        tage = _tage(eintrag)
        if tage is not None and tage > vorschau_tage:
            continue
        vorhanden = posten.get(pid)
        if vorhanden is None:
            posten[pid] = {
                "product_id": pid,
                "name": eintrag.get("product_name") or eintrag.get("name") or f"#{pid}",
                "menge": _zahl(eintrag.get("quantity")),
                "unit": eintrag.get("unit") or "",
                "tage_uebrig": tage,
                "gruende": [eintrag.get("reason") or "laeuft ab"],
            }
            continue
        # Die fruehere Faelligkeit gewinnt: sie ist die, die draengt.
        if tage is not None and (
            vorhanden["tage_uebrig"] is None or tage < vorhanden["tage_uebrig"]
        ):
            vorhanden["tage_uebrig"] = tage
        grund = eintrag.get("reason")
        if grund and grund not in vorhanden["gruende"]:
            vorhanden["gruende"].append(grund)

    geordnet = sorted(
        posten.values(),
        key=lambda p: (p["tage_uebrig"] if p["tage_uebrig"] is not None else 9999, p["name"]),
    )
    for p in geordnet:
        p["abgelaufen"] = p["tage_uebrig"] is not None and p["tage_uebrig"] < 0

    return {
        "erreichbar": True,
        "posten": geordnet,
        "abgelaufen": sum(1 for p in geordnet if p["abgelaufen"]),
        "vorschau_tage": vorschau_tage,
    }
