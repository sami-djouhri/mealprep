"""HTTP-Anschluss an den Fitness-Dienst.

★ Richtung: **Pull**. fitness schiebt bereits das Aktivitaetsniveau hierher
(``fitness/app/services/mealprep_adapter.py``), weil das eine Stufe ist, die
sich selten aendert. "War heute Training" ist dagegen eine tagesbezogene
Frage, die beim Planen gestellt wird und nicht beim Trainieren beantwortet
werden kann.

★★ Was diese Datei mitbehebt: ``routes_api.py`` rief fitness bis zum
2026-09-13 **ohne** ``X-Saganta-Sub``. Der Tagescoach las damit die Trainings
des Vorgabe-Mandanten statt die des angemeldeten Nutzers. Dieselbe Klasse wie
der Fund vom 2026-09-12 im mealprep-Adapter der Gegenrichtung; sie tritt
immer dann auf, wenn ein Aufruf zwischen Diensten irgendwo mitten in einer
Route entsteht statt an einer Stelle, die fuer Aufrufe zustaendig ist.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.tenant_context import current_owner_sub

log = logging.getLogger(__name__)


class FitnessAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        owner_sub: str | None = None,
    ):
        url = base_url if base_url is not None else settings.FITNESS_BASE_URL
        self.base_url = url.rstrip("/") if url else ""
        self.timeout = timeout or settings.FITNESS_TIMEOUT_SEC
        self._owner_sub = owner_sub

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def _client(self) -> httpx.Client:
        headers = {"Accept": "application/json"}
        sub = self._owner_sub or current_owner_sub.get()
        if sub:
            headers["X-Saganta-Sub"] = sub
            # Signiert wird mit dem Geheimnis DES EMPFAENGERS, hier also dem
            # von fitness. Solange es leer ist, verhaelt es sich wie bisher.
            if settings.FITNESS_TENANT_SECRET:
                headers["X-Saganta-Sub-Sig"] = hmac.new(
                    settings.FITNESS_TENANT_SECRET.encode("utf-8"),
                    sub.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=headers,
        )

    # ----- Abfragen (nachsichtig) -----

    def aktivitaetsniveau(self) -> dict | None:
        """Was fitness aus dem echten Training ableitet.

        Felder: ``stufe``, ``faktor``, ``trainings_pro_woche``,
        ``trainings_im_fenster``, ``fenster_tage``, ``belastbar``,
        ``begruendung``.

        ``belastbar`` ist das Feld, auf das es ankommt: fitness sagt damit
        selbst, ob seine Zahl schon etwas taugt. Ohne genug erfasste
        Trainings steht es auf False, und dann darf hier nichts gerechnet
        werden.
        """
        if not self.available:
            return None
        try:
            with self._client() as c:
                resp = c.get("/api/progress/aktivitaetsniveau")
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Fitness nicht erreichbar (aktivitaetsniveau): %s", exc)
            return None

    def tageskontext(self, tag: date) -> dict:
        """Trainings des Tages plus geplanter Tag aus dem aktiven Plan.

        Zog aus ``routes_api._fetch_fitness_context`` hierher um, damit es
        eine Stelle gibt, an der Aufrufe nach fitness entstehen, und damit
        der Mandanten-Header nicht an einer davon fehlen kann.
        """
        if not self.available:
            return {"reachable": False, "planned_day": None, "workouts": []}
        try:
            with self._client() as c:
                w_resp = c.get(
                    "/api/workouts",
                    params={
                        "date_from": tag.isoformat(),
                        "date_to": tag.isoformat(),
                        "limit": 20,
                    },
                )
                w_resp.raise_for_status()
                workouts = w_resp.json()
                if isinstance(workouts, dict):
                    workouts = workouts.get("items", [])

                p_resp = c.get("/api/plans")
                p_resp.raise_for_status()
                aktiver = next(
                    (p for p in p_resp.json() if p.get("is_active")), None
                )

                geplanter_tag = None
                if aktiver:
                    d_resp = c.get(f"/api/plans/{aktiver['id']}")
                    d_resp.raise_for_status()
                    tage = d_resp.json().get("days", [])
                    geplanter_tag = next(
                        (d for d in tage if d.get("day_of_week") == tag.weekday()),
                        None,
                    )
                    if geplanter_tag is None and tage:
                        geordnet = sorted(tage, key=lambda d: d.get("sort_order", 0))
                        geplanter_tag = geordnet[tag.weekday() % len(geordnet)]

                return {
                    "reachable": True,
                    "active_plan": aktiver,
                    "planned_day": geplanter_tag,
                    "workouts": workouts,
                }
        except Exception as exc:
            log.warning("Fitness-Kontext nicht erreichbar: %s", exc)
            return {
                "reachable": False,
                "error": str(exc),
                "planned_day": None,
                "workouts": [],
            }

    def ist_trainingstag(self, tag: date) -> dict[str, Any]:
        """War oder ist an diesem Tag Training?

        ``quelle`` sagt, worauf die Antwort beruht:

        - ``erfasst``: an dem Tag wurde tatsaechlich trainiert. Das ist die
          einzige harte Auskunft.
        - ``geplant``: der aktive Plan sieht fuer diesen Wochentag einen
          Trainingstag vor. Gilt fuer heute und die Zukunft.
        - ``keine``: weder noch, oder fitness antwortet nicht.

        Der Unterschied zwischen "geplant" und "erfasst" ist wichtig genug,
        um ihn weiterzureichen: ein Tagesziel, das einen geplanten und dann
        ausgefallenen Trainingstag als Training rechnet, liegt zu hoch.
        """
        kontext = self.tageskontext(tag)
        if not kontext.get("reachable"):
            return {"training": False, "quelle": "keine", "erreichbar": False}
        workouts = kontext.get("workouts") or []
        if workouts:
            return {
                "training": True,
                "quelle": "erfasst",
                "erreichbar": True,
                "abgeschlossen": any(w.get("finished_at") for w in workouts),
                "anzahl": len(workouts),
            }
        if kontext.get("planned_day"):
            return {
                "training": True,
                "quelle": "geplant",
                "erreichbar": True,
                "abgeschlossen": False,
                "name": (kontext["planned_day"] or {}).get("name"),
            }
        return {"training": False, "quelle": "keine", "erreichbar": True}
