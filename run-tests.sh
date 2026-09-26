#!/usr/bin/env bash
# Testlauf von mealprep.
#
# Gelaufen wird in einem Wegwerf-Container aus dem GEBAUTEN Image, nicht gegen
# eine Host-Umgebung. Das ist Absicht und folgt der Lehre aus dem Saganta-Lauf
# vom 30.08.2026: ein Test gegen den Quellbaum beweist, dass die Datei stimmt,
# nicht dass der laufende Dienst sie hat.
#
# pytest und httpx gehoeren bewusst NICHT ins Produktionsimage. Sie werden fuer
# den Lauf nach /tmp installiert, wie es der Kalender vormacht. Faellt die
# Installation aus (kein Netz), bricht der Lauf ab, statt stillschweigend
# weniger Tests zu sammeln.
#
# Erwartung: "35 passed" oder mehr. Laeuft eine kleinere Zahl durch, wurde ein
# Modul still uebersprungen. Das ist nicht als gruen zu verbuchen.
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${IMAGE:-mealprep-mealprep}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Image '$IMAGE' fehlt. Erst bauen:  docker compose build"
  exit 1
fi

# tests MUSS unter /app/tests liegen: die Suite importiert `tests.conftest`.
# --user 0:0 nur fuer den Lauf, die Rechte im Quellbaum bleiben unberuehrt.
exec docker run --rm --user 0:0 \
  -v "$PWD/tests:/app/tests:ro" \
  -v "$PWD/app:/app/app:ro" \
  -w /app \
  -e PYTHONPATH=/tmp/p:/app \
  "$IMAGE" \
  sh -c 'pip install -q --target /tmp/p pytest httpx || exit 1
         python -m pytest tests -q -p no:cacheprovider'
