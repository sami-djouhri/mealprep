"""Die Attrappen muessen dieselbe Form haben wie das Original.

★ Warum dieser Test existiert: zweimal hat eine Attrappe einen echten Fehler
zugedeckt, statt ihn zu finden.

- ``search_products`` behauptete ``list[dict]``, ``/api/products`` antwortet
  paginiert. Die Attrappe gab eine Liste zurueck, also war alles gruen
  (gefunden 2026-09-12, mit dem ersten echten Aufrufer).
- ``list_stock`` hatte denselben Fehler und blieb einen Tag laenger
  unentdeckt, weil es ueberhaupt keinen Aufrufer gab (2026-09-13).

Eine Attrappe, die weniger Parameter annimmt als das Original, faellt erst
im Betrieb auf. Deshalb wird hier die Signatur verglichen, nicht das
Verhalten: das Verhalten pruefen die Fachtests, die Form niemand.
"""

from __future__ import annotations

import inspect

from app.services.fitness_adapter import FitnessAdapter
from app.services.lager_adapter import LagerAdapter
from tests.conftest import MockFitnessAdapter, MockLagerAdapter


def _parameter(fn) -> list[str]:
    sig = inspect.signature(fn)
    return [
        name
        for name, p in sig.parameters.items()
        if name != "self" and p.kind is not inspect.Parameter.VAR_KEYWORD
    ]


def _nimmt_alles(fn) -> bool:
    """True, wenn die Signatur ein ``**kwargs`` hat.

    Das ist der zulaessige Ausweg: eine Attrappe mit ``**kwargs`` kann keinen
    Aufruf ablehnen, den das Original annimmt. Sie kann eine Umbenennung
    dafuer auch nicht bemerken, deshalb sollte sie die Ausnahme bleiben.
    """
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in inspect.signature(fn).parameters.values()
    )


def _vergleiche(original: type, attrappe: type, ausnahmen: set[str] = frozenset()):
    abweichungen: list[str] = []
    for name, echt in vars(original).items():
        if name.startswith("_") or not callable(echt):
            continue
        if name in ausnahmen:
            continue
        nachbau = getattr(attrappe, name, None)
        if nachbau is None or nachbau is echt:
            continue  # nicht ueberschrieben, also unveraendert uebernommen
        namen_echt = _parameter(echt)
        namen_mock = _parameter(nachbau)
        if _nimmt_alles(nachbau):
            # Nur der Anfang muss passen, den Rest faengt **kwargs.
            passt = namen_echt[: len(namen_mock)] == namen_mock
        else:
            # Zusaetzliche Parameter mit Vorgabewert sind erlaubt, aber
            # keiner des Originals darf fehlen oder umbenannt sein.
            passt = namen_echt == namen_mock[: len(namen_echt)]
        if not passt:
            abweichungen.append(
                f"{original.__name__}.{name}: echt {namen_echt}, Attrappe {namen_mock}"
            )
    return abweichungen


def test_lager_attrappe_hat_dieselben_signaturen():
    abweichungen = _vergleiche(LagerAdapter, MockLagerAdapter)
    assert not abweichungen, "\n".join(abweichungen)


def test_jede_lager_attrappe_wird_geprueft():
    """Nicht nur die eine aus conftest, sondern jede Unterklasse.

    ★ Ohne diese Fassung haette der Test nur ``MockLagerAdapter`` gedeckt,
    waehrend in den Fachtests weitere Attrappen leben (``LagerMitProdukten``,
    ``LagerOhneAntwort`` in ``test_lager_abgleich.py``). Eine Liste, die man
    von Hand pflegt, ist genau die Stelle, an der die naechste Attrappe fehlt.
    Deshalb wird sie hier nicht gefuehrt, sondern erfragt.

    ⚠️ ``__subclasses__`` sieht nur, was importiert ist. Im vollen Lauf ist
    das alles; laeuft nur diese Datei, prueft der Test entsprechend weniger.
    """
    import tests.test_lager_abgleich  # noqa: F401 - laedt die dortigen Attrappen

    abweichungen: list[str] = []
    for attrappe in LagerAdapter.__subclasses__():
        abweichungen += [
            f"{attrappe.__name__}: {zeile}"
            for zeile in _vergleiche(LagerAdapter, attrappe)
        ]
    assert not abweichungen, "\n".join(abweichungen)


def test_fitness_attrappe_kennt_alle_benutzten_methoden():
    # Die Fitness-Attrappe ist keine Unterklasse, deshalb hier andersherum:
    # jede Methode, die sie anbietet, muss es im Original geben und dort
    # dieselben Parameter haben.
    abweichungen: list[str] = []
    for name, nachbau in vars(MockFitnessAdapter).items():
        if name.startswith("_") or not callable(nachbau):
            continue
        echt = getattr(FitnessAdapter, name, None)
        if echt is None:
            abweichungen.append(f"MockFitnessAdapter.{name} gibt es im Original nicht")
            continue
        namen_echt = _parameter(echt)
        namen_mock = _parameter(nachbau)
        if namen_echt != namen_mock:
            abweichungen.append(
                f"FitnessAdapter.{name}: echt {namen_echt}, Attrappe {namen_mock}"
            )
    assert not abweichungen, "\n".join(abweichungen)


def test_paginierte_antwort_wird_ausgepackt(monkeypatch):
    """Die Form der Antwort ist Teil der Schnittstelle.

    Nachgestellt wird, was lager wirklich schickt: ein Objekt mit ``items``.
    Wer das roh zurueckgibt, laesst Aufrufer ueber die Schluesselnamen
    iterieren ("'str' object has no attribute 'get'").
    """
    import httpx

    seiten = [
        {
            "items": [{"id": 1, "product_id": 7, "quantity": 300.0, "unit": "g"}],
            "total": 2,
            "offset": 0,
            "limit": 1,
        },
        {
            "items": [{"id": 2, "product_id": 7, "quantity": 200.0, "unit": "g"}],
            "total": 2,
            "offset": 1,
            "limit": 1,
        },
    ]
    aufrufe = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/products":
            return httpx.Response(200, json={"items": [{"id": 7, "name": "Reis"}], "total": 1})
        seite = seiten[min(aufrufe["n"], len(seiten) - 1)]
        aufrufe["n"] += 1
        return httpx.Response(200, json=seite)

    adapter = LagerAdapter(base_url="http://lager-test")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url=adapter.base_url, transport=transport),
    )

    produkte = adapter.search_products()
    assert produkte == [{"id": 7, "name": "Reis"}]

    bestand = adapter.bestand_gesamt()
    assert bestand == {(7, "g"): 500.0}, "beide Seiten muessen summiert sein"
