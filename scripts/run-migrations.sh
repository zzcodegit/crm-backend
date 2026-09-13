#!/bin/bash
set -euo pipefail

BACKEND_DIR="/home/crm-backend"
PY="${BACKEND_DIR}/venv/bin/python"

cd "${BACKEND_DIR}"

if [[ ! -x "${PY}" ]]; then
  echo "✗ Не найден python venv: ${PY}"
  echo "  Создайте venv и установите зависимости в /home/crm-backend"
  exit 1
fi

echo "=== CRM DB migrations ==="

# Базовая инициализация (таблицы/группы/админ). Идемпотентно.
if [[ -f "${BACKEND_DIR}/seed_admin.py" ]]; then
  echo "0. seed_admin.py"
  "${PY}" seed_admin.py
  echo ""
fi

echo "1. migrate_*.py"
shopt -s nullglob
files=(migrate_*.py)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "  (нет migrate_*.py — пропускаю)"
  exit 0
fi

IFS=$'\n' sorted=($(printf "%s\n" "${files[@]}" | sort))
unset IFS

for f in "${sorted[@]}"; do
  if [[ ! -f "${f}" ]]; then
    continue
  fi
  echo "→ ${f}"
  "${PY}" "${f}"
done

echo ""
echo "✓ DB migrations completed"

