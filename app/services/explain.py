"""Explanation helpers for decision transparency."""

from __future__ import annotations

from app.schemas import DecisionResult


def format_explanation_text(result: DecisionResult) -> str:
    """Return a human-readable explanation block (German)."""
    lines = [f"Ausgewaehltes Rezept: {result.selected_recipe_name} (ID {result.selected_recipe_id})"]
    if result.explanation:
        lines.append("Gruende:")
        for reason in result.explanation:
            lines.append(f"  - {reason}")
    if result.alternatives:
        lines.append(f"Alternativen: {', '.join(str(a) for a in result.alternatives)}")
    bd = result.score_breakdown.get(str(result.selected_recipe_id))
    if bd:
        lines.append(
            f"Score: {bd.total:.3f} "
            f"(Makro={bd.macro_fit:.3f}, MHD={bd.expiry_util:.3f}, "
            f"Aufwand={bd.effort:.3f}, Slot={bd.slot_compat:.3f}, "
            f"Vielfalt={bd.variety:.3f})"
        )
    return "\n".join(lines)
