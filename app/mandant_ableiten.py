"""Den Mandanten fuer headerlose Aufrufe aus den vorhandenen Daten ableiten.

WOZU
``DEFAULT_OWNER_SUB`` traegt die Kennung eines konkreten Menschen. Seit dem
2026-09-05 steht sie nicht mehr im Quelltext, sondern in der ``.env``, weil
dieses Repo veroeffentlicht werden soll. Damit entstand ein neues Problem: wer
den Dienst baut, bevor die ``.env`` den Wert traegt, bekommt einen Dienst, der
headerlosen Aufrufern leere Antworten gibt. Leer sieht aus wie "nichts da",
nicht wie "nicht konfiguriert".

DIE ABLEITUNG
Traegt die Datenbank genau **einen** Mandanten, dann ist er es. Das ist der Fall
einer bestehenden Ein-Personen-Installation, und genau dort waere die Luecke
schaedlich. Bei mehreren Mandanten wird **nicht geraten**: dann ist "headerlos"
schlicht nicht mehr eindeutig, und die richtige Antwort ist, nichts zu liefern
und es zu sagen. Bei leerer Datenbank gibt es nichts abzuleiten, das ist eine
frische Installation.

★ GEFRAGT WIRD UEBER ALLE MANDANTEN-MODELLE, nicht ueber ein ausgesuchtes.
Der erste Entwurf fragte in mealprep nur ``Recipe`` und bekam immer ``None``:
der Rezept-Katalog ist bewusst geteilt und traegt durchgehend ``owner_sub NULL``.
Ein einzelnes Modell zu waehlen heisst, die Ableitung an einer Eigenheit
aufzuhaengen, die man beim Lesen des Codes nicht sieht. Die Liste unten ist
dieselbe, die auch das Scoping benutzt.

WAS SIE NICHT IST
Kein Ersatz fuer die Konfiguration. Sie schreibt nichts fest, laeuft bei jedem
Start neu und protokolliert, was sie getan hat. Sobald ``.env`` den Wert traegt,
greift sie gar nicht mehr.
"""

import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.tenant import STRICT_MODELS as MODELLE

logger = logging.getLogger(__name__)


def einzigen_mandanten_ableiten() -> str | None:
    """Genau ein Mandant ueber alle Mandanten-Tabellen? Dann seine Kennung."""
    gefunden: set[str] = set()
    try:
        with SessionLocal() as db:
            for modell in MODELLE:
                # skip_tenant: die Abfrage soll ueber ALLE Mandanten sehen. Ohne
                # das filtert das globale Scoping sie auf den aktuellen (leeren)
                # sub und liefert immer null Zeilen. Das waere eine Ableitung,
                # die sich selbst blind macht.
                subs = db.execute(
                    select(modell.owner_sub).distinct().execution_options(skip_tenant=True)
                ).scalars().all()
                gefunden.update(s for s in subs if s)
                if len(gefunden) > 1:
                    break
    except Exception as exc:  # DB noch nicht migriert, Datei fehlt, o.ae.
        logger.warning("Mandant nicht ableitbar (%s)", exc)
        return None

    if len(gefunden) == 1:
        return next(iter(gefunden))
    if len(gefunden) > 1:
        logger.error(
            "DEFAULT_OWNER_SUB ist leer und die Daten tragen mehrere Mandanten. "
            "Es wird nicht geraten: headerlose Aufrufe sehen nichts. "
            "Wert setzen mit saganta/scripts/owner-kennung-eintragen.sh"
        )
    return None
