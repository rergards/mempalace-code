# Handoff: rergards/mempalace-code, 3 октября 2026

Локальный пакет продолжения аудита; product backlog и product code этим пакетом не изменены. Передать полный каталог либо архив вместе с PROMPT.txt. Все ссылки targetHandoff в backlog-import.json рассчитаны на docs/handoffs/greptile-2026-10-03 в продукте. Проверить manifest перед переносом. DraftItem не является native API payload; актуальные schema/owner/tokens устанавливает принимающий агент.

- MP-MINE-K8S-SECRET-SPACING: P1, fix; issues/MP-MINE-K8S-SECRET-SPACING.md.
- MP-MCP-KG-BEFORE-LEASE: P1, fix; issues/MP-MCP-KG-BEFORE-LEASE.md.
- MP-MCP-FILE-CONTEXT-CAP: P2, fix; issues/MP-MCP-FILE-CONTEXT-CAP.md.
- MP-MCP-DEGRADED-RETRY: P2, fix; issues/MP-MCP-DEGRADED-RETRY.md.
- MP-MCP-CACHED-KG-NO-PALACE: P3, fix; issues/MP-MCP-CACHED-KG-NO-PALACE.md.
- MP-MAINTENANCE-THREAD-BYPASS: P1, recheck; issues/MP-MAINTENANCE-THREAD-BYPASS.md.
- MP-ARCHIVE-PUBLISH-RACE: P2, recheck; issues/MP-ARCHIVE-PUBLISH-RACE.md.

Пять новых MemPalace дефектных условий воспроизведены на frozen source. Границы и controls каждого пункта находятся в его handoff. Две старые гонки переданы как recheck и уже могли быть исправлены; duplicate intake запрещён. Hold не входит в автоматическую очередь.

Проверки текущего product root из его рабочей директории (аудиторские check scripts ожидают старое defect presence; ожидаемый acceptance продукта задан отдельно):

```sh
python3 -B docs/handoffs/greptile-2026-10-03/checks/mempalace_mcp_runtime.py --source .
python3 -B docs/handoffs/greptile-2026-10-03/checks/mempalace_reader_pagination.py --source .
python3 -B docs/handoffs/greptile-2026-10-03/checks/mempalace_secret_yaml.py --source .
python3 -B docs/handoffs/greptile-2026-10-03/checks/mempalace_maintenance_lease_race.py --source .
python3 -B docs/handoffs/greptile-2026-10-03/checks/mempalace_archive_publish_race.py --source .
```

Каждая команда читается вместе с AGENTS.md продукта и ownership gate. Копии исходных ответов и разбор находятся в evidence/. Полное чтение targets — provider self-report, остальные supplied files частичные/UNKNOWN. Полный аудит продукта не завершён. Greptile остановлен после explicit trial_limit_reached даже на Base; автоматических новых запросов нет.
