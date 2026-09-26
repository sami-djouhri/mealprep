"""HTTP client for the Lager inventory service.

★★ **Hier steht bewusst nur, was auch gerufen wird.** Am 2026-09-13 hatten vier
Methoden null Aufrufer (``get_product``, ``list_stock``, ``consume``,
``get_consumption_stats``), und zweimal hatte genau dort ein Formfehler
jahrelang gelegen: ``search_products`` und ``list_stock`` behaupteten beide
``list[dict]``, waehrend lager paginiert antwortet. Ein Adapter ohne Aufrufer
wird von keinem Test und keinem Betrieb widerlegt, seine Typangaben sind
Behauptungen. Die vier sind deshalb entfernt worden, nicht auskommentiert.

Wer eine davon braucht, baut sie neu **gegen die dann gemessene Antwortform**
(``openapi.json`` des laufenden lager), nicht aus dieser Datei zurueck.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.config import settings
from app.domain import DomainError
from app.tenant_context import current_owner_sub

log = logging.getLogger(__name__)


class LagerUnavailable(Exception):
    """Raised when the Lager service cannot be reached."""


class LagerAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        owner_sub: str | None = None,
    ):
        url = base_url or settings.LAGER_BASE_URL
        self.base_url = url.rstrip("/") if url else ""
        self.timeout = timeout or settings.LAGER_TIMEOUT_SEC
        # Optionaler expliziter Tenant; sonst greift der Request-Kontext (_client).
        self._owner_sub = owner_sub
        # Einmal geholter Bestand, aus dem `get_available` dann antwortet.
        # None = keiner geladen (jeder Aufruf geht ueber HTTP).
        self._schnappschuss: dict[tuple[int, str], float] | None = None
        # Dasselbe fuer die Verbrauchsraten, aus denen `get_turnover` antwortet.
        self._raten: dict[int, dict] | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def _client(self) -> httpx.Client:
        # Multiuser: den Request-owner_sub als X-Saganta-Sub an lager propagieren,
        # damit Bestand/Verbrauch im Tenant des jeweiligen Nutzers landen (statt
        # headerlos auf lager's DEFAULT_OWNER_SUB zu fallen). Explizit übergebener
        # owner_sub hat Vorrang vor dem Request-Kontext.
        headers = {"Accept": "application/json"}
        sub = self._owner_sub or current_owner_sub.get()
        if sub:
            headers["X-Saganta-Sub"] = sub
            # ★ Echtheitsnachweis mit dem Geheimnis DES LAGERS (nicht dem
            # eigenen): signiert wird fuer den Empfaenger. Ohne diese Zeile
            # bricht der Weg in dem Moment, in dem lager
            # TENANT_HEADER_ENFORCE=1 bekommt, und zwar als 401 mitten in der
            # Einkaufsliste. Solange LAGER_TENANT_SECRET leer ist, verhaelt es
            # sich wie bisher.
            if settings.LAGER_TENANT_SECRET:
                headers["X-Saganta-Sub-Sig"] = hmac.new(
                    settings.LAGER_TENANT_SECRET.encode("utf-8"),
                    sub.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=headers,
        )

    # ----- query methods (graceful degradation) -----

    def search_products(
        self, q: str | None = None, category: str | None = None, limit: int = 500
    ) -> list[dict]:
        """Produkte aus dem Lager.

        ★ ``/api/products`` antwortet **paginiert**: ein Objekt mit
        ``items``, ``total``, ``offset``, ``limit``. Diese Methode gab die
        Antwort frueher roh zurueck und behauptete per Annotation trotzdem
        ``list[dict]``. Wer darueber iteriert, bekommt dann die
        Schluesselnamen als Zeichenketten und scheitert mit
        "'str' object has no attribute 'get'".

        Aufgefallen ist das erst am 2026-09-12 mit dem ersten echten
        Aufrufer; die Attrappe in den Tests (``tests/conftest.py``) gibt eine
        Liste zurueck und hat die Abweichung deshalb zugedeckt.
        """
        if not self.available:
            return []
        try:
            params: dict[str, Any] = {"limit": limit}
            if q:
                params["q"] = q
            if category:
                params["category"] = category
            with self._client() as c:
                resp = c.get("/api/products", params=params)
                resp.raise_for_status()
                daten = resp.json()
            if isinstance(daten, dict):
                return daten.get("items", [])
            return daten
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (search_products): %s", exc)
            return []

    @property
    def hat_schnappschuss(self) -> bool:
        return self._schnappschuss is not None

    def schnappschuss_laden(self, erneuern: bool = False) -> bool:
        """Den Bestand EINMAL holen; ``get_available`` antwortet danach daraus.

        ★★ Der Anlass, gemessen am 2026-09-13: das Erzeugen einer
        Einkaufsliste machte einen HTTP-Aufruf **je Zutat**. Bei 47 Zutaten
        plus Regeln und Vorlauf waren das rund fuenfzig Anfragen in wenigen
        Sekunden, und lager deckelt bei 60 je Minute und Absender. Der Rest
        kam als **429** zurueck, und ``get_available`` macht aus jedem Fehler
        eine 0. Die Liste wurde also aus lauter Nullen gebaut und sah dabei
        vollkommen plausibel aus: alles musste gekauft werden, nichts war da.

        Zwei Dinge trafen zusammen, und beide allein waeren harmlos gewesen:
        eine Schleife, die pro Element ruft, und eine Nachsicht, die einen
        Fehler in einen Messwert verwandelt.

        Der Schnappschuss ist deckungsgleich mit dem Endpunkt, nicht nur
        aehnlich: ``/api/stock/available`` summiert ``quantity`` ueber Zeilen
        mit **genau** dieser Einheit und rechnet nichts um. Genau das tut
        ``bestand_gesamt`` auch.

        Rueckgabe False heisst: nicht geladen, es bleibt beim Einzelabruf.
        Der Aufrufer muss entscheiden, ob er auf dieser Grundlage weiterrechnen
        will.

        ⚠️ Der Aufruf ist ohne ``erneuern`` **wiederholbar ohne Wirkung**,
        damit ihn mehrere Schleifen unabhaengig voneinander anstossen koennen.
        Das setzt voraus, dass ein Adapter nicht laenger lebt als eine
        Anfrage, und so wird er ueberall gebaut (``LagerAdapter()`` je Route).
        Wer ihn laenger haelt, sieht einen alten Bestand und muss selbst
        ``schnappschuss_verwerfen`` rufen.
        """
        if self._schnappschuss is not None and not erneuern:
            return True
        self._schnappschuss = self.bestand_gesamt()
        return self._schnappschuss is not None

    def schnappschuss_verwerfen(self) -> None:
        self._schnappschuss = None

    def get_available(self, product_id: int, unit: str = "g") -> float:
        if self._schnappschuss is not None:
            return self._schnappschuss.get((product_id, unit), 0.0)
        if not self.available:
            return 0.0
        try:
            with self._client() as c:
                resp = c.get(
                    "/api/stock/available",
                    params={"product_id": product_id, "unit": unit},
                )
                resp.raise_for_status()
                data = resp.json()
                return float(data.get("total", 0.0))
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (get_available %d): %s", product_id, exc)
            return 0.0

    def get_expiring(self, days: int = 7) -> list[dict]:
        if not self.available:
            return []
        try:
            with self._client() as c:
                resp = c.get("/api/stock/expiring", params={"days": days})
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (get_expiring): %s", exc)
            return []

    def get_critical(self) -> list[dict]:
        """Was im Lager gerade dringend ist (abgelaufen, MHD kritisch, leer).

        ``/api/critical`` existiert seit Langem und wurde von hier nie
        gerufen; life-ops liest es, mealprep nicht. Die Antwort ist ein
        Objekt mit dem Schluessel ``critical``, keine blanke Liste.
        """
        if not self.available:
            return []
        try:
            with self._client() as c:
                resp = c.get("/api/critical")
                resp.raise_for_status()
                daten = resp.json()
            if isinstance(daten, dict):
                return daten.get("critical", [])
            return daten
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (get_critical): %s", exc)
            return []

    def get_suggestions(
        self, analysis_days: int = 30, expiring_within_days: int = 7
    ) -> list[dict]:
        """Lagers eigene Einkaufsvorschlaege.

        ★ ``/api/shopping-list`` klingt nach einer zweiten gespeicherten
        Liste, ist aber keine: lager rechnet bei jedem Abruf aus
        Mindestbestand, Wochenverbrauch und Ablaufdatum. Es gibt dort nichts
        zum Abhaken und nichts, was zwischen zwei Abrufen bestehen bleibt.
        Damit ist es keine konkurrierende Wahrheit, sondern eine Quelle, die
        mealprep bisher nicht gelesen hat.

        Felder je Eintrag: ``product_id``, ``product_name``,
        ``suggested_quantity``, ``unit``, ``reason``, ``current_stock``.
        """
        if not self.available:
            return []
        try:
            with self._client() as c:
                resp = c.get(
                    "/api/shopping-list",
                    params={
                        "analysis_days": analysis_days,
                        "expiring_within_days": expiring_within_days,
                    },
                )
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (get_suggestions): %s", exc)
            return []

    def _stock_seiten(
        self,
        product_id: int | None = None,
        location: str | None = None,
        only_positive: bool = True,
        limit: int = 500,
        max_seiten: int = 20,
    ) -> list[list[dict]]:
        """Bestandsseiten nacheinander holen. Leere Liste bei Ausfall."""
        if not self.available:
            return []
        seiten: list[list[dict]] = []
        try:
            params: dict[str, Any] = {"only_positive": only_positive, "limit": limit}
            if product_id is not None:
                params["product_id"] = product_id
            if location is not None:
                params["location"] = location
            with self._client() as c:
                offset = 0
                for _ in range(max_seiten):
                    resp = c.get("/api/stock", params={**params, "offset": offset})
                    resp.raise_for_status()
                    daten = resp.json()
                    if isinstance(daten, list):  # aeltere Fassung ohne Seiten
                        seiten.append(daten)
                        break
                    posten = daten.get("items", [])
                    seiten.append(posten)
                    offset += len(posten)
                    if not posten or offset >= int(daten.get("total", 0)):
                        break
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (list_stock): %s", exc)
            return []
        return seiten

    def bestand_gesamt(self) -> dict[tuple[int, str], float] | None:
        """Der ganze Bestand in EINEM Durchlauf, summiert je (Produkt, Einheit).

        ★ Warum das noetig ist: ``get_available`` ist ein HTTP-Aufruf je
        Produkt. Die Einkaufsliste zeigt Dutzende Zeilen, und jede wuerde beim
        Anzeigen einzeln nachfragen. Das ist nicht nur langsam, es macht den
        Anzeigeweg auch von Dutzenden Gelegenheiten zum Scheitern abhaengig
        statt von einer.

        ★★ ``None`` heisst **nicht gemessen**, ``{}`` heisst **gemessen und
        leer**. Der Unterschied ist hier kein Feinschliff: wer einen Ausfall
        als leeren Vorrat liest, setzt jede Zeile der Einkaufsliste auf ihren
        vollen geplanten Betrag und laesst das wie eine Messung aussehen.
        """
        seiten = self._stock_seiten()
        if not seiten:
            return None if self.available else {}
        summe: dict[tuple[int, str], float] = {}
        for posten in seiten:
            for eintrag in posten:
                try:
                    pid = int(eintrag["product_id"])
                    einheit = str(eintrag.get("unit") or "g")
                    menge = float(eintrag.get("quantity") or 0.0)
                except (KeyError, TypeError, ValueError):
                    continue
                summe[(pid, einheit)] = summe.get((pid, einheit), 0.0) + menge
        return summe

    # ----- mutation methods (raise on failure) -----

    def einbuchen(
        self,
        product_id: int,
        menge: float,
        unit: str = "g",
        mhd: str | None = None,
        ort: str | None = None,
        notiz: str | None = None,
    ) -> dict:
        """Einkauf in den Bestand buchen (``POST /api/stock``).

        ★ Die Gegenrichtung zu ``consume_recipe``. Bis 2026-09-13 gab es sie
        nicht: mealprep buchte beim Kochen ab und **nie** wieder auf, der
        rechnerische Bestand lief gegen null, und das sah wie ein leerer
        Vorrat aus statt wie eine fehlende Kopplung.
        """
        if not self.available:
            raise LagerUnavailable("Lager nicht konfiguriert")
        body: dict[str, Any] = {
            "product_id": product_id,
            "quantity": menge,
            "unit": unit,
        }
        if mhd:
            body["mhd"] = mhd
        if ort:
            body["location"] = ort
        if notiz:
            body["lot_note"] = notiz
        try:
            with self._client() as c:
                resp = c.post("/api/stock", json=body)
                if resp.status_code == 422:
                    daten = resp.json()
                    raise DomainError(
                        daten.get("error", "Einbuchen fehlgeschlagen"),
                        daten.get("details", {}),
                    )
                resp.raise_for_status()
                return resp.json()
        except DomainError:
            raise
        except (httpx.HTTPError, Exception) as exc:
            raise LagerUnavailable(f"Lager nicht erreichbar: {exc}") from exc

    def einbuchung_zuruecknehmen(self, stock_entry_id: int) -> bool:
        """Einen von hier erzeugten Bestandseintrag wieder entfernen.

        Nur fuer die Ruecknahme eines Hakens gedacht, deshalb die enge
        Signatur: zurueckgenommen wird genau der Eintrag, dessen Nummer beim
        Abhaken gemerkt wurde, nichts Gesuchtes.
        """
        if not self.available:
            raise LagerUnavailable("Lager nicht konfiguriert")
        try:
            with self._client() as c:
                resp = c.delete(f"/api/stock/{stock_entry_id}")
                if resp.status_code == 404:
                    return False
                resp.raise_for_status()
                return True
        except (httpx.HTTPError, Exception) as exc:
            raise LagerUnavailable(f"Lager nicht erreichbar: {exc}") from exc

    def consume_recipe(
        self,
        ingredients: list[dict],
        source: str = "mealprep",
        ref_type: str = "recipe",
        ref_id: int | None = None,
    ) -> list[dict]:
        if not self.available:
            raise LagerUnavailable("Lager nicht konfiguriert")
        items = []
        for ing in ingredients:
            item: dict[str, Any] = {
                "product_id": ing["product_id"],
                "amount": ing["amount"],
                "unit": ing["unit"],
                "reason": "verbraucht",
                "source": source,
                "ref_type": ref_type,
            }
            if ref_id is not None:
                item["ref_id"] = ref_id
            items.append(item)
        body = {"ingredients": items}
        try:
            with self._client() as c:
                resp = c.post("/api/stock/consume-recipe", json=body)
                if resp.status_code == 422:
                    data = resp.json()
                    raise DomainError(
                        data.get("error", "Lager-Rezeptverbrauch fehlgeschlagen"),
                        data.get("details", {}),
                    )
                resp.raise_for_status()
                return resp.json()
        except DomainError:
            raise
        except (httpx.HTTPError, Exception) as exc:
            raise LagerUnavailable(f"Lager nicht erreichbar: {exc}") from exc

    # ----- turnover (graceful degradation) -----

    def verbrauchsraten(self, days: int = 30) -> dict[int, dict] | None:
        """Alle Verbrauchsraten in EINEM Abruf, je Produktnummer.

        ★★ Zweiter Fall derselben Familie wie ``bestand_gesamt``, gemessen am
        2026-09-13: ``calculate_days_of_food`` rief ``get_turnover`` einmal je
        verknuepfter Zutat. Ein Dashboard-Aufruf kostete damit 17 Anfragen an
        lager, 14 davon Turnover, bei einem Deckel von 60 je Minute. Das
        reichte fuer drei Aufrufe, und was danach kam, war nicht langsamer,
        sondern falsch: der 429 wurde hier unten zu ``avg_daily: 0``, und eine
        Null ist von einer Messung nicht mehr zu unterscheiden.

        ★★ ``None`` heisst **nicht gemessen**, ``{}`` heisst **gemessen und
        nichts bewegt**. Wer den Ausfall als "kein Verbrauch" liest, bekommt
        einen Vorrat, der rechnerisch ewig haelt.

        Ein Produkt ohne Verbrauch im Zeitraum fehlt in der Antwort. Das ist
        die Auskunft von lager, nicht ein Verlust: dort steht dann keine Rate.
        """
        if not self.available:
            return {}
        try:
            with self._client() as c:
                resp = c.get("/api/stats/turnover", params={"days": days})
                if resp.status_code == 404:
                    # Uebergangssicherung: ein lager ohne den Sammelabruf. Kein
                    # stiller Rueckfall, sondern eine Zeile im Protokoll, sonst
                    # laeuft die Schleife unbemerkt weiter.
                    log.warning(
                        "Lager kennt /api/stats/turnover nicht (alte Fassung). "
                        "Es bleibt beim Aufruf je Produkt."
                    )
                    return None
                resp.raise_for_status()
                zeilen = resp.json()
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (verbrauchsraten): %s", exc)
            return None
        raten: dict[int, dict] = {}
        for zeile in zeilen if isinstance(zeilen, list) else []:
            try:
                pid = int(zeile["product_id"])
            except (KeyError, TypeError, ValueError):
                continue
            raten[pid] = {
                "avg_daily": float(zeile.get("avg_daily", 0) or 0),
                "unit": zeile.get("unit", ""),
            }
        return raten

    @property
    def hat_raten(self) -> bool:
        return self._raten is not None

    def raten_laden(self, days: int = 30, erneuern: bool = False) -> bool:
        """Die Verbrauchsraten EINMAL holen; ``get_turnover`` liest danach daraus.

        Gegenstueck zu ``schnappschuss_laden`` fuer den Bestand, mit derselben
        Bedingung: der Adapter darf nicht laenger leben als eine Anfrage, sonst
        antwortet er aus einem alten Stand.

        Rueckgabe False heisst: nicht geladen, es bleibt beim Einzelabruf.
        """
        if self._raten is not None and not erneuern:
            return True
        self._raten = self.verbrauchsraten(days=days)
        return self._raten is not None

    def raten_verwerfen(self) -> None:
        self._raten = None

    def get_turnover(self, product_id: int, days: int = 30) -> dict:
        """Return avg daily consumption for a product.

        Returns {"avg_daily": float, "unit": str}.
        Gracefully returns {"avg_daily": 0, "unit": ""} on failure.

        ⚠️ Diese Nachsicht ist der Grund, warum ``raten_laden`` existiert: hier
        unten laesst sich ein Ausfall nicht mehr von "kein Verbrauch"
        unterscheiden. Wer die Unterscheidung braucht, fragt oben nach.
        """
        if self._raten is not None:
            return self._raten.get(product_id, {"avg_daily": 0, "unit": ""})
        if not self.available:
            return {"avg_daily": 0, "unit": ""}
        try:
            with self._client() as c:
                resp = c.get(
                    f"/api/stats/turnover/{product_id}",
                    params={"days": days},
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "avg_daily": float(data.get("avg_daily", 0)),
                    "unit": data.get("unit", ""),
                }
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (get_turnover %d): %s", product_id, exc)
            return {"avg_daily": 0, "unit": ""}

    # ----- stats (graceful degradation) -----

    def get_expiry_forecast(self) -> list[dict]:
        if not self.available:
            return []
        try:
            with self._client() as c:
                resp = c.get("/api/stats/expiry-forecast")
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Lager nicht erreichbar (expiry_forecast): %s", exc)
            return []
