"""HTTP client for the Kalender service (day-type lookups)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class KalenderAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        feed_token: str | None = None,
        timeout: int | None = None,
    ):
        url = base_url or settings.KALENDER_BASE_URL
        self.base_url = url.rstrip("/") if url else ""
        self.feed_token = feed_token or settings.KALENDER_FEED_TOKEN
        self.timeout = timeout or settings.KALENDER_TIMEOUT_SEC

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.feed_token)

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )

    def _fetch_day_type(self, client: httpx.Client, day: date) -> str:
        resp = client.get(
            "/api/day-type",
            params={"date": day.isoformat(), "token": self.feed_token},
        )
        resp.raise_for_status()
        return resp.json().get("type", "frei")

    def get_day_type(self, day: date) -> str:
        """Return day type for a date. Defaults to 'frei' on error."""
        if not self.available:
            return "frei"
        try:
            with self._client() as c:
                return self._fetch_day_type(c, day)
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Kalender nicht erreichbar (get_day_type %s): %s", day, exc)
            return "frei"

    def get_day_types_range(self, start: date, days: int = 7) -> dict[date, str]:
        """Return day types for a range of dates.

        MP2: teilt EINEN httpx.Client fuer alle Tage (Connection-Reuse statt pro
        Tag ein neuer Client). Der Range wird pro Dashboard-Poll aufgerufen.
        Pro-Tag fail-soft ('frei'); faellt der Client-Aufbau ganz aus, alle 'frei'.
        """
        result: dict[date, str] = {}
        if not self.available:
            for i in range(days):
                result[start + timedelta(days=i)] = "frei"
            return result
        try:
            with self._client() as c:
                for i in range(days):
                    d = start + timedelta(days=i)
                    try:
                        result[d] = self._fetch_day_type(c, d)
                    except (httpx.HTTPError, Exception) as exc:
                        log.warning("Kalender day-type %s: %s", d, exc)
                        result[d] = "frei"
        except (httpx.HTTPError, Exception) as exc:
            log.warning("Kalender range nicht erreichbar: %s", exc)
            for i in range(days):
                result.setdefault(start + timedelta(days=i), "frei")
        return result

    def needs_packed_lunch(self, day: date) -> bool:
        """True if day is 'arbeit' and NOT Friday (short day)."""
        if day.weekday() == 4:  # Friday
            return False
        return self.get_day_type(day) == "arbeit"
