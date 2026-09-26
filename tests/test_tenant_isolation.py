"""Tests fuer das Tenant-Scoping (app/tenant.py): Basis-Isolation.

GELTUNGSBEREICH (ehrlich): sichert ab, dass das ORM-Tenant-Scoping aktiv ist und
fremde subs 0 STRICT-Zeilen sehen (faengt Entfernen/Brechen des Scopings).
Reproduziert NICHT die Cache-Poisoning-Variante des 2026-07-06-Bugs
(with_loader_criteria ohne Lambda), nur langlebiger Prozess/warmer Cache; live
verifiziert (fremder sub -> 0 nach Deploy). Der Lambda-Fix bleibt im Code.
"""

from datetime import date

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.tenant as tenant
from app.db import Base
from app.models import GoalPhase


def _make_sessionmaker():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    event.listen(Sess, "do_orm_execute", tenant._apply_tenant_scope)
    event.listen(Sess, "before_flush", tenant._stamp_tenant)
    return Sess


def _count(Sess, sub):
    s = Sess()
    s.info["owner_sub"] = sub
    try:
        return s.scalar(select(func.count()).select_from(GoalPhase))
    finally:
        s.close()


def test_tenant_isolation_foreign_sub_sees_nothing():
    Sess = _make_sessionmaker()
    seed = Sess()
    seed.info["owner_sub"] = "ownerA"
    seed.add(GoalPhase(name="Cut", start_date=date(2026, 1, 1)))
    seed.add(GoalPhase(name="Bulk", start_date=date(2026, 3, 1)))
    seed.commit()
    seed.close()

    assert _count(Sess, "ownerA") == 2
    assert _count(Sess, "FOREIGN-XYZ") == 0
    assert _count(Sess, "ownerA") == 2


def test_before_flush_stamps_owner_sub():
    Sess = _make_sessionmaker()
    s = Sess()
    s.info["owner_sub"] = "ownerB"
    g = GoalPhase(name="Maintain", start_date=date(2026, 5, 1))
    s.add(g)
    s.commit()
    assert g.owner_sub == "ownerB"
    s.close()
