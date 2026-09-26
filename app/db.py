from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.backend_auth import sub_from_bearer
from app.config import settings
from app.tenant_auth import loese_owner_sub
from app.tenant_context import current_owner_sub

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db(request: Request) -> Session:  # type: ignore[misc]
    # ⚠️ MUSS async sein: der current_owner_sub.set() unten propagiert sonst NICHT
    # zum Route-Handler. FastAPI führt sync-Generator-Dependencies (plain `def … yield`)
    # im Threadpool aus → das ContextVar-set landet in einer Kontext-Kopie und
    # verpufft; die LagerAdapter-Handler (alle sync `def`) sähen den Default →
    # App-zu-App-Calls fielen headerlos auf lager's DEFAULT_OWNER_SUB (Multiuser-Bug).
    # Empirisch verifiziert (fastapi 0.139/starlette 1.3): async-gen-dep propagiert
    # zu sync UND async Handlern, sync-gen-dep zu keinem.
    # SessionLocal()/db.close() sind I/O-frei (SQLite) → kein Event-Loop-Block; die
    # eigentlichen Queries laufen weiter im sync-Handler-Threadpool.
    # Siehe Memory feedback_fastapi_contextvar_sync_dep.
    # Tenant an die Session binden. Drei Pfade (wie lager):
    #  1. Nativer Client: `Authorization: Bearer <HS256-JWT>` (aud=mealprep-api) →
    #     fail-closed verifiziert (jeder Fehler = 401, KEIN Default-Fallback).
    #  2. Web via app-proxy: `X-Saganta-Sub`-Header (better-auth-sub), seit
    #     2026-09-05 mit HMAC-Signatur pruefbar (app/tenant_auth.py, FCS-01).
    #  3. Interne/headerlose Aufrufe → DEFAULT_OWNER_SUB (bisheriges Verhalten).
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        owner_sub = sub_from_bearer(authorization)
    else:
        owner_sub = loese_owner_sub(request)

    db = SessionLocal()
    db.info["owner_sub"] = owner_sub
    # Auch im Request-Kontext ablegen, damit App-zu-App-Calls (LagerAdapter →
    # lager) den echten Nutzer-Sub als X-Saganta-Sub propagieren (Multiuser).
    # set() OHNE reset(): FastAPI führt den yield-Cleanup u.U. in einem anderen
    # Context aus → reset(token) würfe "created in a different Context". Der Wert
    # wird bei jedem Request neu gesetzt (vor jeder LagerAdapter-Nutzung), daher
    # kein Leak; Default bleibt None → headerless → DEFAULT_OWNER_SUB.
    current_owner_sub.set(owner_sub)
    try:
        yield db  # type: ignore[misc]
    finally:
        db.close()
