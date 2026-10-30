"""Core domain primitives: errors, unit helpers."""

from __future__ import annotations


class DomainError(Exception):
    """Raised for business-rule violations. Carries machine-readable details."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ---------------------------------------------------------------------------
# Unit helpers (MVP: g, ml, piece)
# ---------------------------------------------------------------------------

VALID_UNITS = {"g", "ml", "piece"}

# Trivial 1:1 aliases keep the door open for kg->g later.
UNIT_ALIASES: dict[str, str] = {
    "gram": "g",
    "grams": "g",
    "milliliter": "ml",
    "milliliters": "ml",
    "stueck": "piece",
    "stk": "piece",
    "pcs": "piece",
}


def normalise_unit(raw: str) -> str:
    low = raw.strip().lower()
    return UNIT_ALIASES.get(low, low)


def assert_unit_compatible(a: str, b: str) -> None:
    na, nb = normalise_unit(a), normalise_unit(b)
    if na != nb:
        raise DomainError(
            f"Einheiten inkompatibel: {a!r} vs {b!r}",
            {"unit_a": a, "unit_b": b},
        )
