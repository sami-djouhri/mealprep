from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./app.db"

    # Multi-Tenant.
    # Mandant fuer headerlose interne Aufrufer (life-ops, assets-api).
    #
    # ★ Leer als Vorbelegung, seit 2026-09-05. Vorher stand hier die Kennung
    # eines konkreten Menschen. Sie gehoert nicht in ein Repo, das
    # veroeffentlicht werden soll, und ein Selbsthoster hat ohnehin eine andere.
    # Wert kommt aus .env, eingetragen von
    # saganta/scripts/owner-kennung-eintragen.sh.
    #
    # Leer heisst fail-closed: headerlose Aufrufe sehen dann nichts, statt
    # stillschweigend die Daten irgendeines Kontos zu sehen. Beim Start wird
    # einmal gewarnt (app/main.py), damit der Zustand nicht unbemerkt bleibt.
    DEFAULT_OWNER_SUB: str = ""

    # Native Apps: HS256-Backend-JWT (aud=mealprep-api) vom saganta-auth-service.
    # Muss == SAGANTA_BACKEND_SECRET des auth-service sein (Wert NUR in der .env des Wirts).
    # Leer => Bearer-Auth deaktiviert (nur Header/Default-Pfad, bisheriges Verhalten).
    SAGANTA_BACKEND_SECRET: str = ""

    # Lager integration
    LAGER_BASE_URL: str = ""
    LAGER_TIMEOUT_SEC: int = 5

    # Decision engine defaults
    DEFAULT_MAX_COOK_TIME_MIN: int = 30
    EXPIRY_THRESHOLD_DAYS: int = 7

    # Stock forecast
    MIN_DAYS_FOOD: int = 3

    # Auto-snack settings
    SNACK_DEFICIT_THRESHOLD: float = 0.15  # 15% under daily target -> snack
    MAX_SNACKS_PER_DAY: int = 2

    # Shopping: min stock runway after planned meals
    MIN_STOCK_RUNWAY_DAYS: int = 3

    # Kalender integration
    KALENDER_BASE_URL: str = ""
    KALENDER_FEED_TOKEN: str = ""
    KALENDER_TIMEOUT_SEC: int = 5
    PLAN_HORIZON_DAYS: int = 7

    # Fitness integration
    FITNESS_BASE_URL: str = "http://fitness:8000"
    FITNESS_TIMEOUT_SEC: int = 5

    # Tagesbezogener Bedarf: Anteil, der vom Ruhetag auf den Trainingstag
    # wandert. NICHT ein Aufschlag obendrauf - der Aktivitaetsfaktor im TDEE
    # enthaelt das Training bereits, und ein Aufschlag wuerde es doppelt
    # zaehlen. Verschoben wird so, dass die Wochensumme gleich bleibt.
    # 0 schaltet die Tagesunterscheidung ab.
    TRAININGSTAG_ANTEIL: float = 0.10

    # Echtheitsnachweis fuer den X-Saganta-Sub-Header (app/tenant_auth.py).
    # Eigenes Geheimnis je Dienst. Leer => bisheriges Verhalten, Header gilt
    # ungeprueft. TENANT_HEADER_ENFORCE: 0 = beobachten, 1 = 401 erzwingen.
    # Erst scharf schalten, wenn die Protokolle ueber Tage still bleiben.
    MEALPREP_TENANT_SECRET: str = ""
    # Geheimnis DES LAGERS, um ausgehende Aufrufe dorthin zu signieren
    # (app/services/lager_adapter.py). Nicht das eigene: signiert wird
    # immer fuer den Empfaenger. Leer => wie bisher, ohne Signatur.
    LAGER_TENANT_SECRET: str = ""
    # Dasselbe fuer ausgehende Aufrufe nach fitness
    # (app/services/fitness_adapter.py).
    FITNESS_TENANT_SECRET: str = ""
    TENANT_HEADER_ENFORCE: int = 0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
