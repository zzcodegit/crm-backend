# MIGRATION: Pricelist MKL

## Что добавлено

- Новый независимый каталог `Прайс МКЛ`.
- Новые таблицы:
  - `pricelist_mkl_groups`
  - `pricelist_mkl_items`

## Применение

Из директории backend:

```bash
python migrate_pricelist_mkl.py
```

## Примечания

- Миграция идемпотентна (`CREATE TABLE IF NOT EXISTS`).
- Структура полей повторяет каталоги `Прайс склад` и `Прайс RX`.
