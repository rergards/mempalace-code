# MP-MCP-FILE-CONTEXT-CAP

P2, confirmed на frozen MemPalace 7c8a506a2401cd2eaad474e8d3499055af27ab06. Run audit-id-withheld, Plus.

reader.py _rows_for (303-310) использует _MAX_SOURCE_ROWS=10000. tool_file_context строит total и next_offset только из полученных rows. При 10001 индексированном chunk клиент получает total=10000, страницу offset=9900 с 100 chunks и next_offset=null. Оставшийся chunk недоступен.

Нарушенный внешний контракт: описание MCP TOOL_SPECS.mempalace_file_context обещает total для всех chunks файла и next_offset=null на последней странице.

Проверка: реальные reader.py и AST owner tool_file_context, inert metadata store; 10001 rows дали указанный результат. Контроль 9999 rows дал правильные total=9999 и 99 chunks последней страницы. Живой LanceDB не использовался.

```sh
python3 checks/mempalace_reader_pagination.py --source .raw/mempalace-2026-10-02/git-source
```

Приёмка: каждый индексированный chunk достижим последовательными страницами; total и next_offset описывают весь source. Проверить границы 9999,10000,10001 и большие offsets. Сохранить ограниченную стоимость запроса и точность ordering по chunk_index; увеличение скрытого лимита не устанавливает полноту. Проверить consumers общего resolve_source_rows.

Перед backlog intake проверить актуальный код и дубликаты. Изменения продукта этим аудитом не выполнены.
