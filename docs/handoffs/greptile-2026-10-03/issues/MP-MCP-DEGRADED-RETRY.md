# MP-MCP-DEGRADED-RETRY: Непригодная Lance таблица получает подсказку повторить вызов

Приоритет: P2. Статус: confirmed на frozen snapshot.

Source SHA: 7c8a506a2401cd2eaad474e8d3499055af27ab06. Greptile run: audit-id-withheld, Plus.

Owner: mempalace_code/mcp/runtime.py:206-220; mempalace_code/storage.py:2133-2147,2679-2683.

После ошибки cached scan свежий read-only open подавляет ошибку db.open_table и оставляет _table=None. count_by_pair возвращает пустой dict; _degraded_response сообщает, что palace переоткрыт, и предлагает retry. Неоткрываемая таблица сохраняется, повтор может снова дать ту же ошибку.

## Проверка

Исполнены реальные AST owners LanceStore._open_or_create/count_by_pair и runtime._degraded_response; DB boundary инертно выдавал corrupt-table OSError. Получена retry hint при _table=None. Контроль с исключением самого open_store дал health/repair hint. Живой LanceDB/повреждённые пользовательские данные не использовались.

Команда из локального audit repository:

```sh
python3 checks/mempalace_mcp_runtime.py --source .raw/mempalace-2026-10-02/git-source
```

## Приёмка

Recovery отличает здоровый переоткрытый store от отсутствующей/неоткрываемой таблицы; здоровый store получает retry, повреждённый получает recovery guidance. Сохранить read-only характер проверки и корректную обработку отсутствующего palace.

При переносе в продуктовый backlog сначала проверить current working tree, дубликаты и текущие исправления. Продуктовые изменения этим аудитом не выполнены. Контрпроверка: на актуальном коде повторить тот же trigger с disposable palace и убедиться, что нарушенный контракт восстановлен.
