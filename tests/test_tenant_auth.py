"""Echtheitspruefung des X-Saganta-Sub-Headers (app/tenant_auth.py).

Sichert den Sicherheitsfix von 2026-09-05 ab (Audit-Befund FCS-01): der
Header-Pfad in ``app/db.py`` nahm den Mandanten bisher ungeprueft entgegen,
waehrend der Bearer-Pfad daneben fail-closed verifiziert. Wer :8096 direkt
erreichte, konnte sich als beliebiger Mandant ausgeben.

Jeder Test prueft **beide** Richtungen: dass der richtige Weg traegt UND dass
der falsche abgewiesen wird. Eine Pruefung, die nur den Erfolgsfall kennt, ist
bei Zugriffsrechten wertlos, sie bleibt gruen, wenn die Sperre ganz fehlt.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import tenant_auth
from app.config import settings
from app.tenant_auth import erwartete_signatur, loese_owner_sub

GEHEIM = "prueflauf-geheimnis"
SUB = "MANDANT-A"
FREMD = "MANDANT-B"


def anfrage(**header):
    """Minimale Attrappe: loese_owner_sub liest ausschliesslich request.headers."""
    return SimpleNamespace(headers={k.lower().replace("_", "-"): v for k, v in header.items()})


def signiert(sub, secret=GEHEIM):
    return anfrage(**{"x-saganta-sub": sub, "x-saganta-sub-sig": erwartete_signatur(sub, secret)})


# --- Zustand 1: kein Geheimnis konfiguriert (Auslieferungszustand) ------------

def test_ohne_geheimnis_gilt_der_header_wie_bisher(monkeypatch):
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", "")
    assert loese_owner_sub(anfrage(**{"x-saganta-sub": SUB})) == SUB


def test_ohne_header_immer_der_vorgabe_mandant(monkeypatch):
    """Headerlose interne Aufrufer (life-ops, assets-api) bleiben unberuehrt."""
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    assert loese_owner_sub(anfrage()) == settings.DEFAULT_OWNER_SUB
    assert loese_owner_sub(None) == settings.DEFAULT_OWNER_SUB


# --- Zustand 2: Geheimnis gesetzt, Beobachtung -------------------------------

def test_gueltige_signatur_traegt(monkeypatch):
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    monkeypatch.setattr(settings, "TENANT_HEADER_ENFORCE", 0)
    assert loese_owner_sub(signiert(SUB)) == SUB


def test_beobachtung_laesst_unsigniertes_durch_und_protokolliert(monkeypatch, caplog):
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    monkeypatch.setattr(settings, "TENANT_HEADER_ENFORCE", 0)
    with caplog.at_level("WARNING", logger=tenant_auth.logger.name):
        assert loese_owner_sub(anfrage(**{"x-saganta-sub": SUB})) == SUB
    assert "ohne Signatur" in caplog.text


# --- Zustand 3: Erzwingen ----------------------------------------------------

def test_erzwingen_lehnt_unsigniertes_ab(monkeypatch):
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    monkeypatch.setattr(settings, "TENANT_HEADER_ENFORCE", 1)
    with pytest.raises(HTTPException) as f:
        loese_owner_sub(anfrage(**{"x-saganta-sub": SUB}))
    assert f.value.status_code == 401


def test_erzwingen_laesst_signiertes_durch(monkeypatch):
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    monkeypatch.setattr(settings, "TENANT_HEADER_ENFORCE", 1)
    assert loese_owner_sub(signiert(SUB)) == SUB


# --- Der Punkt des Verfahrens: die Signatur haengt am Sub --------------------

def test_abgefangene_signatur_oeffnet_keinen_fremden_mandanten(monkeypatch):
    """Signatur fuer SUB, Header sagt FREMD. Muss scheitern."""
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    monkeypatch.setattr(settings, "TENANT_HEADER_ENFORCE", 1)
    gestohlen = anfrage(
        **{"x-saganta-sub": FREMD, "x-saganta-sub-sig": erwartete_signatur(SUB, GEHEIM)}
    )
    with pytest.raises(HTTPException) as f:
        loese_owner_sub(gestohlen)
    assert f.value.status_code == 401


def test_falsches_geheimnis_traegt_nicht(monkeypatch):
    monkeypatch.setattr(settings, "MEALPREP_TENANT_SECRET", GEHEIM)
    monkeypatch.setattr(settings, "TENANT_HEADER_ENFORCE", 1)
    with pytest.raises(HTTPException):
        loese_owner_sub(signiert(SUB, secret="anderes-geheimnis"))


def test_signatur_ist_je_sub_verschieden():
    assert erwartete_signatur(SUB, GEHEIM) != erwartete_signatur(FREMD, GEHEIM)
