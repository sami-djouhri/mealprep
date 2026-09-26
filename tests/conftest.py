"""Shared test fixtures: in-memory SQLite session + MockLagerAdapter."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import *  # noqa: F401,F403
from app.services.lager_adapter import LagerAdapter


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


class MockLagerAdapter(LagerAdapter):
    """In-memory mock that replaces HTTP calls with dictionary lookups.

    ★ Diese Attrappe ist zweimal zur Fehlerquelle geworden, nicht zur
    Absicherung: ``search_products`` und ``list_stock`` gaben hier eine Liste
    zurueck, waehrend lager paginiert antwortet, und die Tests waren gruen,
    obwohl der echte Aufruf gescheitert waere. Deshalb gilt hier: die
    Signaturen muessen zum echten Adapter passen (``test_attrappe_treu.py``
    prueft das), und wo lager eine Form liefert, liefert die Attrappe
    dieselbe.
    """

    def __init__(self):
        super().__init__(base_url="http://mock-lager", timeout=1)
        self._stock: dict[tuple[int, str], float] = {}
        self._expiring: list[dict] = []
        self._suggestions: list[dict] = []
        self._critical: list[dict] = []
        self._forecast: list[dict] = []
        #: Verbrauchsraten je Produkt, wie sie der Sammelabruf liefert.
        self._raten_daten: dict[int, dict] = {}
        #: Produktkatalog, wie ihn `/api/products` liefert (ausgepackt).
        self._produkte: list[dict] = []
        #: Alles, was ueber ``einbuchen`` hereinkam, in Reihenfolge.
        self.eingebucht: list[dict] = []
        self._naechste_entry_id = 900
        #: Auf True setzen, um einen Lager-Ausfall nachzustellen.
        self.ausgefallen = False

    def set_stock(self, product_id: int, unit: str, qty: float) -> None:
        self._stock[(product_id, unit)] = qty

    def set_expiring(self, entries: list[dict]) -> None:
        self._expiring = entries

    def set_suggestions(self, entries: list[dict]) -> None:
        self._suggestions = entries

    def set_critical(self, entries: list[dict]) -> None:
        self._critical = entries

    def set_forecast(self, entries: list[dict]) -> None:
        self._forecast = entries

    def set_turnover(self, product_id: int, avg_daily: float, unit: str = "g") -> None:
        self._raten_daten[product_id] = {"avg_daily": avg_daily, "unit": unit}

    # Override query methods
    def get_available(self, product_id: int, unit: str = "g") -> float:
        return self._stock.get((product_id, unit), 0.0)

    def get_expiring(self, days: int = 7) -> list[dict]:
        return self._expiring

    def search_products(self, q=None, category=None, limit: int = 500) -> list[dict]:
        return list(self._produkte)

    def set_produkte(self, produkte: list[dict]) -> None:
        self._produkte = produkte

    def bestand_gesamt(self) -> dict[tuple[int, str], float] | None:
        if self.ausgefallen:
            return None
        return dict(self._stock)

    def verbrauchsraten(self, days: int = 30) -> dict[int, dict] | None:
        if self.ausgefallen:
            return None
        return dict(self._raten_daten)

    def get_turnover(self, product_id: int, days: int = 30) -> dict:
        # Nachgebaut statt geerbt: sonst versucht das Original einen echten
        # HTTP-Aufruf, sobald ein Test `get_turnover` ohne `raten_laden` ruft.
        quelle = self._raten if self._raten is not None else self._raten_daten
        return quelle.get(product_id, {"avg_daily": 0, "unit": ""})

    def get_suggestions(
        self, analysis_days: int = 30, expiring_within_days: int = 7
    ) -> list[dict]:
        return self._suggestions

    def get_critical(self) -> list[dict]:
        return self._critical

    # Override mutation methods
    def _abbuchen(self, product_id, amount, unit="g") -> list[dict]:
        """Interner Helfer der Attrappe.

        ★ Hiess bis zum 2026-09-13 ``consume`` und spiegelte damit eine
        Methode des echten Adapters. Die ist entfernt worden (null Aufrufer),
        also ist dies jetzt ein Helfer der Attrappe und kein Nachbau mehr.
        """
        key = (product_id, unit)
        avail = self._stock.get(key, 0.0)
        if avail < amount - 0.001:
            from app.domain import DomainError
            raise DomainError("Nicht genug Bestand", {"product_id": product_id})
        self._stock[key] = avail - amount
        return [{"id": 1, "stock_entry_id": 1, "amount": amount, "unit": unit}]

    def consume_recipe(self, ingredients, **kwargs) -> list[dict]:
        events = []
        for ing in ingredients:
            events.extend(self._abbuchen(ing["product_id"], ing["amount"], ing["unit"]))
        return events

    def einbuchen(
        self, product_id, menge, unit="g", mhd=None, ort=None, notiz=None
    ) -> dict:
        if self.ausgefallen:
            from app.services.lager_adapter import LagerUnavailable
            raise LagerUnavailable("Attrappe: Lager ausgefallen")
        self._naechste_entry_id += 1
        key = (product_id, unit)
        self._stock[key] = self._stock.get(key, 0.0) + menge
        eintrag = {
            "id": self._naechste_entry_id,
            "product_id": product_id,
            "quantity": menge,
            "unit": unit,
            "mhd": mhd,
            "location": ort,
            "lot_note": notiz,
        }
        self.eingebucht.append(eintrag)
        return eintrag

    def einbuchung_zuruecknehmen(self, stock_entry_id: int) -> bool:
        for i, e in enumerate(self.eingebucht):
            if e["id"] == stock_entry_id:
                key = (e["product_id"], e["unit"])
                self._stock[key] = max(0.0, self._stock.get(key, 0.0) - e["quantity"])
                self.eingebucht.pop(i)
                return True
        return False

    def get_expiry_forecast(self) -> list[dict]:
        return self._forecast


class MockFitnessAdapter:
    """Attrappe fuer den Fitness-Anschluss.

    Absichtlich keine Unterklasse von ``FitnessAdapter``: hier wird nur
    festgelegt, was fitness antwortet, und jede Methode, die mealprep
    braucht, muss bewusst hier stehen. ``test_attrappe_treu.py`` haelt die
    Signaturen gegen das Original.
    """

    def __init__(self, niveau=None, trainingstag=None, erreichbar: bool = True):
        self.available = True
        self._niveau = niveau
        self._trainingstag = trainingstag
        self._erreichbar = erreichbar

    def aktivitaetsniveau(self) -> dict | None:
        return self._niveau if self._erreichbar else None

    def ist_trainingstag(self, tag) -> dict:
        if not self._erreichbar:
            return {"training": False, "quelle": "keine", "erreichbar": False}
        if self._trainingstag is None:
            return {"training": False, "quelle": "keine", "erreichbar": True}
        return dict(self._trainingstag)

    def tageskontext(self, tag) -> dict:
        if not self._erreichbar:
            return {"reachable": False, "planned_day": None, "workouts": []}
        return {"reachable": True, "planned_day": None, "workouts": []}


@pytest.fixture
def mock_lager():
    return MockLagerAdapter()
