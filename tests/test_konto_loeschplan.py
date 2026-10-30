"""Der Abdeckungs-Riegel des Loeschwegs.

Er braucht keine Daten und keine laufende Datenbank: das Soll kommt aus den
SQLAlchemy-Metadaten, also aus den Modellen dieses Dienstes. Wird er rot, ist
eine Tabelle hinzugekommen, die den Mandanten traegt, aber in keinem Schritt von
``app/konto.py`` steht -- oder ein Kind hat sein ``ondelete="CASCADE"`` verloren.

Die Antwort darauf ist nie "Test anpassen". Entweder bekommt die Tabelle einen
Schritt, oder sie wird ausdruecklich als gemeinsamer Bestand erklaert. Ohne
diesen Riegel faellt eine neue Tabelle still aus dem Loeschweg, und ein Lauf
meldet weiterhin Erfolg.
"""

from app import konto_mechanik as mechanik
from app import models  # noqa: F401  (fuellt Base.metadata)
from app.db import Base
from app.konto import PLAN


def test_der_loeschplan_deckt_alle_tabellen_ab():
    assert mechanik.abdeckung_pruefen(PLAN, Base.metadata) == []


def test_jeder_schritt_nennt_eine_bekannte_tabelle():
    """Ein Tippfehler im Tabellennamen trifft nie und meldet trotzdem 0 Zeilen."""
    bekannt = set(Base.metadata.tables)
    for schritt in PLAN.schritte:
        assert schritt.tabelle in bekannt, (
            f"Schritt nennt '{schritt.tabelle}', das es in den Modellen nicht gibt"
        )


def test_leere_metadaten_brechen_laut():
    """Blinde Pruefung ist schlimmer als keine, denn sie meldet "sauber"."""
    import pytest
    from sqlalchemy import MetaData

    with pytest.raises(RuntimeError):
        mechanik.abdeckung_pruefen(PLAN, MetaData())


def test_plan_und_scoping_liste_beschreiben_dasselbe():
    """Gegenprobe gegen die zweite Liste, die es hier schon gibt.

    ``app/tenant.py`` fuehrt ``STRICT_MODELS`` und ``HYBRID_MODELS`` fuer das Select-Scoping, ``konto.py``
    die Loeschschritte. Beide beantworten "was gehoert einem Mandanten". Laufen
    sie auseinander, ist entweder das Scoping undicht oder der Loeschweg
    unvollstaendig, und beides sieht im Betrieb normal aus.
    """
    from app import tenant

    im_scoping = {m.__tablename__ for m in tenant.STRICT_MODELS + tenant.HYBRID_MODELS}
    im_plan = {s.tabelle for s in PLAN.schritte}
    fehlt_im_plan = im_scoping - im_plan
    assert not fehlt_im_plan, (
        f"im Scoping, aber in keinem Loeschschritt: {sorted(fehlt_im_plan)}"
    )
