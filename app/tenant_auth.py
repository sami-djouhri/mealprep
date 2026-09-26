"""Echtheitspruefung des ``X-Saganta-Sub``-Headers.

**Das Problem, das hier adressiert wird** (Audit-Befund FCS-01, Juli 2026): In
``app/db.py`` gibt es zwei Wege, einen Mandanten zu bestimmen, und nur einer
prueft etwas nach. Der ``Authorization: Bearer``-Pfad verifiziert ein HS256-JWT
fail-closed (``app/backend_auth.py``). Der Header-Pfad nahm den Wert bisher
ungeprueft entgegen. Damit haengt die gesamte Mandantentrennung an der Annahme,
dass der app-proxy der einzige Weg zum Dienst ist. Wer ``:8096`` direkt
erreicht, konnte sich mit einem beliebigen ``X-Saganta-Sub`` als fremder Mandant
ausgeben, und das ORM-Scoping in ``app/tenant.py`` glaubt ihm.

Der Absender schickt zusaetzlich
``X-Saganta-Sub-Sig: hex(HMAC-SHA256(secret, sub))``. Die Signatur haengt an
genau diesem Sub, eine abgefangene laesst sich nicht auf einen fremden umhaengen,
und das Geheimnis wandert nie ueber die Leitung.

**Eigenes Geheimnis je Dienst** (``MEALPREP_TENANT_SECRET``), nicht ein gemeinsames:
wer mealprep lesen darf, soll damit nicht automatisch die anderen Dienste
lesen duerfen.

Drei Zustaende:

1. **Kein Geheimnis konfiguriert** (Auslieferungszustand): verhaelt sich **exakt
   wie vorher**. Kein Zwang, keine Warnung, sonst waere der Betrieb ab dem ersten
   Deploy voller Rauschen, und Rauschen hat hier schon einmal einen echten
   Ausfall verdeckt.
2. **Geheimnis gesetzt, ``TENANT_HEADER_ENFORCE=0``** (Beobachtung): Unsigniertes
   wird akzeptiert und protokolliert. So sieht man vor dem Scharfschalten, welcher
   Absender noch nachziehen muss.
3. **Geheimnis gesetzt, ``TENANT_HEADER_ENFORCE=1``**: alles Unsignierte gibt 401,
   kein stiller Rueckfall auf den Owner.

**Unberuehrt in allen drei Zustaenden:** Aufrufe *ohne* ``X-Saganta-Sub``. Das
sind die internen, headerlosen Pfade (life-ops, Einkaufsliste), sie laufen weiter
auf ``DEFAULT_OWNER_SUB``. Ebenso unberuehrt der Bearer-Pfad, der schon prueft.

★ Der Text dieses Moduls ist absichtlich deckungsgleich mit
``kalender/backend/tenant_auth.py`` und ``postfach/app/tenant_auth.py``. Es sind
getrennte Repos, deshalb getrennte Kopien; eine Aenderung am Verfahren gehoert in
alle.
"""

import hashlib
import hmac
import logging

from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

SUB_HEADER = "x-saganta-sub"
SIG_HEADER = "x-saganta-sub-sig"


def erwartete_signatur(sub: str, secret: str) -> str:
    """Die Signatur, die ein Absender fuer diesen Sub mitschicken muss."""
    return hmac.new(secret.encode("utf-8"), sub.encode("utf-8"), hashlib.sha256).hexdigest()


def loese_owner_sub(request) -> str:
    """Mandant fuer diesen Request. Wirft 401 nur im Erzwingen-Modus."""
    if request is None:
        return settings.DEFAULT_OWNER_SUB

    sub = request.headers.get(SUB_HEADER)
    if not sub:
        # Headerloser Pfad: interne Aufrufer. Unveraendert.
        return settings.DEFAULT_OWNER_SUB

    secret = settings.MEALPREP_TENANT_SECRET
    if not secret:
        # Noch kein Geheimnis vergeben: wie bisher, ohne Rauschen.
        return sub

    mitgeschickt = request.headers.get(SIG_HEADER, "")
    if mitgeschickt and hmac.compare_digest(mitgeschickt, erwartete_signatur(sub, secret)):
        return sub

    grund = "ohne Signatur" if not mitgeschickt else "mit falscher Signatur"
    if settings.TENANT_HEADER_ENFORCE:
        logger.warning("Mandanten-Header %s abgelehnt (sub=%s...)", grund, sub[:8])
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "X-Saganta-Sub ohne gueltige Signatur",
        )
    logger.warning(
        "Mandanten-Header %s akzeptiert (Beobachtungsphase, sub=%s...). Absender nachziehen, "
        "bevor TENANT_HEADER_ENFORCE=1 gesetzt wird",
        grund,
        sub[:8],
    )
    return sub
