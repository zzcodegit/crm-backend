#!/bin/bash
# Проверка PostgreSQL + API; при сбое БД — попытка поднять кластер. Бэкенд не перезапускаем.
set -euo pipefail

LOG_TAG="crm-healthcheck"
fail=0

if ! pg_isready -q 2>/dev/null; then
  logger -t "${LOG_TAG}" "PostgreSQL not ready, ensuring pg_logical dirs and starting cluster"
  /home/crm-backend/scripts/ensure-pg-logical-dirs.sh || true
  systemctl start postgresql@16-main 2>/dev/null || true
  sleep 3
  if ! pg_isready -q 2>/dev/null; then
    logger -t "${LOG_TAG}" "PostgreSQL still down after start attempt"
    fail=1
  fi
fi

if [[ "${fail}" -eq 0 ]]; then
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:8000/api/health 2>/dev/null || true)
  if [[ -z "${code}" || "${code}" != "200" ]]; then
    logger -t "${LOG_TAG}" "API health returned ${code:-unreachable} (crm-backend not restarted automatically)"
  fi
fi

exit "${fail}"
