# MP-MCP-KG-BEFORE-LEASE: MCP mine создаёт KG до захвата write lease

Приоритет: P1. Статус: confirmed на frozen snapshot.

Source SHA: 7c8a506a2401cd2eaad474e8d3499055af27ab06. Greptile run: audit-id-withheld, Plus.

Owner: mempalace_code/mcp/tools/write.py:249-254; mempalace_code/mcp/runtime.py:74-86,294-310; mempalace_code/knowledge_graph.py:483-493,875-900.

Первый вызов mine с валидным проектом и незакэшированным KG вычисляет kg=_get_kg(create=True) до входа в _mine_quiet. open_palace_kg создаёт SQLite и может выполнять legacy adoption. Если write lease отказал, ответ busy сообщает Nothing was written, хотя SQLite уже существует.

## Проверка

На реальном frozen owner tool_mine и реальном SQLite KG, с inert отказом lease: KG отсутствовал до вызова, существовал при входе в отказавшую lease и остался после busy. Конкурентный живой writer и legacy adoption в этой проверке не запускались.

Команда из локального audit repository:

```sh
python3 checks/mempalace_mcp_runtime.py --source .raw/mempalace-2026-10-02/git-source
```

## Приёмка

При отказе lease состояние palace/KG не меняется. No-op mine не создаёт KG и не запускает adoption. Нужное создание/открытие выполняется внутри существующей write lease; использовать актуальный owner и имеющийся LazyKnowledgeGraph, если его контракт подходит.

При переносе в продуктовый backlog сначала проверить current working tree, дубликаты и текущие исправления. Продуктовые изменения этим аудитом не выполнены. Контрпроверка: на актуальном коде повторить тот же trigger с disposable palace и убедиться, что нарушенный контракт восстановлен.
