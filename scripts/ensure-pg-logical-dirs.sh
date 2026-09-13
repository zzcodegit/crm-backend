#!/bin/bash
# Восстанавливает каталоги pg_logical после аварийного shutdown (иначе PostgreSQL 16 не стартует).
set -euo pipefail

PGDATA="${PGDATA:-/var/lib/postgresql/16/main}"
LOGICAL="${PGDATA}/pg_logical"

for sub in snapshots mappings; do
  dir="${LOGICAL}/${sub}"
  if [[ ! -d "${dir}" ]]; then
    install -d -o postgres -g postgres -m 0700 "${dir}"
    logger -t crm-pg-fix "Created missing ${dir}"
  fi
done
