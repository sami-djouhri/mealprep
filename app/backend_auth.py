"""Verifikation des Saganta-Backend-JWT (HS256) fuer native Clients.

Der saganta-auth-service stellt via ``GET /api/mobile/token?aud=mealprep-api`` ein
kurzlebiges HS256-JWT aus (issueBackendToken: ``iss='saganta'``, ``aud='mealprep-api'``,
``sub``, ``exp``). Native Apps schicken es als ``Authorization: Bearer <jwt>``.

Web-Aufrufe laufen weiter ueber den app-proxy (``X-Saganta-Sub``-Header, kein
Bearer) und interne Aufrufer headerlos: beide Pfade bleiben unberuehrt (siehe
``app/db.py``). Fail-closed: ein *vorhandener* Bearer, der nicht valide ist,
fuehrt zu 401 (kein Fallback auf DEFAULT_OWNER_SUB): noetig, sobald mealprep
oeffentlich (``mealprep-api.saganta.de``) erreichbar ist.

Bewusst stdlib-only (hmac/hashlib/base64/json), keine externe JWT-Lib noetig.
Gespiegelt aus lager/app/backend_auth.py (nur ``_AUDIENCE`` differiert).
"""

import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException, status

from app.config import settings

_ISSUER = "saganta"
_AUDIENCE = "mealprep-api"
_CLOCK_SKEW_SEC = 30


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _unauth(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


def sub_from_bearer(authorization: str) -> str:
    """Validiert das ``Bearer``-JWT und liefert den ``sub``. Wirft 401 bei jedem
    Fehler (fail-closed)."""
    secret = settings.SAGANTA_BACKEND_SECRET
    if not secret:
        raise _unauth("backend auth not configured")

    token = authorization[len("Bearer "):].strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise _unauth("malformed token")
    header_b64, payload_b64, sig_b64 = parts

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig_b64)
    except Exception as exc:  # noqa: BLE001
        raise _unauth("bad signature encoding") from exc
    if not hmac.compare_digest(expected, got):
        raise _unauth("bad signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise _unauth("bad payload") from exc

    if payload.get("iss") != _ISSUER:
        raise _unauth("bad issuer")

    aud = payload.get("aud")
    if aud != _AUDIENCE and not (isinstance(aud, list) and _AUDIENCE in aud):
        raise _unauth("bad audience")

    exp = payload.get("exp")
    try:
        if exp is None or time.time() > float(exp) + _CLOCK_SKEW_SEC:
            raise _unauth("expired")
    except (TypeError, ValueError) as exc:
        raise _unauth("bad exp") from exc

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise _unauth("no sub")
    return sub
