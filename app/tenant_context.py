"""Request-scoped Tenant-Kontext (owner_sub) für App-zu-App-Calls.

Der aktuelle ``owner_sub`` wird in ``get_db`` (app/db.py) pro Request gesetzt und
vom ``LagerAdapter`` gelesen, damit App-zu-App-Calls (mealprep → lager) den echten
Nutzer-Sub als ``X-Saganta-Sub`` propagieren, statt headerlos auf lager's
``DEFAULT_OWNER_SUB`` zu fallen (Multiuser-Korrektheit, sonst gleicht jeder Nutzer
gegen dasselbe Default-Lager ab). Ein explizit übergebener ``owner_sub`` hat Vorrang.

Bewusst ein eigenes, import-freies Modul, um Zirkular-Importe (db ↔ lager_adapter)
zu vermeiden.
"""

import contextvars

current_owner_sub: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_owner_sub", default=None
)
