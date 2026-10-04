# MP-MAINTENANCE-THREAD-BYPASS

Статус: подтверждён. Приоритет: P1, нарушение исключения записи во время maintenance.

Репозиторий: https://github.com/rergards/mempalace-code
Исходный репозиторий на source workspace: <product-root>.
Проверенный SHA: 7c8a506a2401cd2eaad474e8d3499055af27ab06.
Greptile run: audit-id-withheld; comment comment-1790956567429-dchhgph.
Владелец: mempalace_code/operation_lock.py, held_in_process и palace_write_lease.

## Проблема и контракт

Контракт модуля и palace_write_lease требует исключать palace writes при exclusive installation maintenance. Проверка install.held_in_process() учитывает lease любого потока процесса. Поэтому поток B пропускает acquire_shared, когда exclusive maintenance lease держит поток A. Per-palace RLock защищает другой ресурс и эту гонку не закрывает.

## Доказательство

На фактическом модуле: поток A держит install.acquire_exclusive("maintenance"); поток B входит в palace_write_lease(..., wait=0) до освобождения maintenance. Ошибки отсутствуют. Положительный контроль: отдельный поток с прямым install.acquire_shared(..., wait=0) корректно получает OperationLockedError под тем же exclusive lease. POSIX fcntl доступен. Все lock files размещены в временном каталоге; настоящие install leases, palace и watchers не затронуты.

```sh
python3 <audit-checks>/mempalace_maintenance_lease_race.py --source <audit-source>
```

Текущий результат: exit 1, direct_shared=["blocked"], palace_write_entered_during_maintenance=true, threads_completed=true. Exit 2 означает неподдержанную платформу или непройденный контроль и не доказывает исправление.

## Критерии исправления

- Поток без собственной разрешённой lease не входит в palace write под exclusive maintenance другого потока.
- Сохранить существующую разрешённую вложенность writer одного потока и явный fence inheritance wing-migration child.
- Сохранить per-palace сериализацию, блокировку между процессами, wait/deadline и освобождение lease после ошибок.
- Проверить конфликт двух потоков, обычную запись, nested write и разрешённый inheritance на временных lock paths.

## Область и authority

Минимальный предполагаемый delta относится к существующему владельцу reentrancy/lease и его тестам. Новый сервис, внешний lock store и изменение maintenance workflow не требуются для постановки этой проблемы. Этот review не разрешает продуктовые изменения, backlog mutation, commit, push, release или работу с live palace.

При принятии проверить drift, дубликаты и текущий контракт. Восстановление: git -C <product-root> status --short, затем сверить HEAD. Отчёт и скрипт находятся на ноутбуке; продуктовый репозиторий — на source workspace.
