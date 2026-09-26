"""Goal phase service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GoalPhase


class GoalsService:
    def __init__(self, db: Session):
        self.db = db

    def get_active(self) -> GoalPhase | None:
        return self.db.execute(
            select(GoalPhase).where(GoalPhase.is_active.is_(True))
        ).scalar_one_or_none()

    def list_all(self) -> list[GoalPhase]:
        return self.db.execute(select(GoalPhase)).scalars().all()
