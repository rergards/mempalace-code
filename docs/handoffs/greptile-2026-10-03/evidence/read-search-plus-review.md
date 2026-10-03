# Поиск и чтение: второй focused Plus

Run audit-id-withheld, COMPLETED, Plus, billableCredits=3. Время 22:01:50.754Z — 22:07:03.572Z, 312.818 секунды, 2 октября 2026. Frozen MemPalace 7c8a506a2401cd2eaad474e8d3499055af27ab06, base 3594fbce1050bd0471a3e3b40ed6ebe72473a440.

Провайдер сообщил FULLY_READ для reader.py 1-280/281-535, searcher.py 1-300/301-586, search_reranker.py 1-119, mcp/tools/search.py 1-220/221-438, tests/test_reader.py 1-260/261-510/511-714. Все 2392 строки названы. Это self-report; trace полного чтения API не даёт. Остальные supporting files прочитаны выборочно.

Оговорки провайдера: previous-review comparison не разрешён, git diff без аргументов был invalid/empty, начальный bulk diff обрезан. Провайдер сообщил продолжение чтения пяти целей по materialized HEAD; однострочный security input обрезан и его advisory entries не проверены. Эти supporting omissions не превращаются в полное покрытие. reviewedBaseSha совпадает с запросом; current target hashes перед запуском совпали с source workspace.

## Dispositions

- Concurrent archive can be overwritten: duplicate MP-ARCHIVE-PUBLISH-RACE; уже подтверждён отдельно. Здесь сохранён frozen код; незакоммиченные исправления source workspace этот run не проверяет. Новая задача не создаётся.
- Ambiguous source selects a file: specification-dependent. Поведение воспроизведено: CWD-relative exact match получает приоритет, другой CWD даёт ambiguous_source. Это прямо предусмотрено resolve_source_rows docstring (relative input resolves against working directory; exact matches preferred). MCP описание допускает прочтение, что любой shared suffix ambiguous. Нарушение принятого однозначного контракта не установлено; P1 не подтверждён и handoff на исправление не создан. Требуется решение владельца о semantics либо уточнение документации.
- File context stops at 10000: confirmed P2, новый handoff MP-MCP-FILE-CONTEXT-CAP.md. 10001 inert indexed rows дают total=10000 и next_offset=null при оставшемся chunk. Контроль ниже границы корректен.

## Ошибка опроса и recovery

GET статуса получил HTTP 503. Локальный poller остановился; новый POST не выполнялся. Helper получил ограниченные retries для transient GET 429/5xx и transport timeout. Возобновление GET того же run завершилось успешно. Первичная ошибка сохранена в ignored read-search-plus-api-error.json; request/correlation/run ID сохранены. POST остаётся однократным; duplicate submission отсутствует.

## Решение

Два connected Plus дали по пять явных coverage rows и воспроизводимые условия. Размер около 2400-2700 строк пригоден для дальнейших пилотов; полнота остаётся provider-reported. Не дробить весь репозиторий автоматически. Следующий приоритет после двух MemPalace участков: текущая authentication path Warhammer. Зафиксировать новый committed dev; незакоммиченные server changes исключить.
