# MP-MCP-CACHED-KG-NO-PALACE: Cached KG пропускает отсутствие palace

Приоритет: P3. Статус: confirmed на frozen snapshot.

Source SHA: 7c8a506a2401cd2eaad474e8d3499055af27ab06. Greptile run: audit-id-withheld, Plus.

Owner: mempalace_code/mcp/runtime.py:74-86; mempalace_code/mcp/tools/kg.py:43,151.

Долгоживущая MCP-сессия уже имеет _kg. Оператор удаляет/перемещает palace. _get_kg возвращает cached object без _palace_dir_exists; следующий SQLite stats/query даёт OperationalError вместо NoPalaceError и штатной подсказки.

## Проверка

Реальный SQLite KG открыт во временном palace; затем directory перемещён внутри disposable audit fixture. Cached getter вернул объект и stats дал OperationalError. Контроль с _kg=None дал NoPalaceError. Потеря данных не утверждается. Приоритет Greptile P2 снижен до P3: редкая внешняя операция и ухудшение recovery response.

Команда из локального audit repository:

```sh
python3 checks/mempalace_mcp_runtime.py --source .raw/mempalace-2026-10-02/git-source
```

## Приёмка

Cached и cold KG read после отсутствия palace дают одинаковый no-palace контракт без создания directory/SQLite. Проверить совместимость с restore/recreate того же path; не вводить новый lifecycle owner.

При переносе в продуктовый backlog сначала проверить current working tree, дубликаты и текущие исправления. Продуктовые изменения этим аудитом не выполнены. Контрпроверка: на актуальном коде повторить тот же trigger с disposable palace и убедиться, что нарушенный контракт восстановлен.
