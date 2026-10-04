# MP-MINE-K8S-SECRET-SPACING

P1, confirmed. Frozen MemPalace 7c8a506a2401cd2eaad474e8d3499055af27ab06. Greptile run audit-id-withheld, Base.

Owner: mempalace_code/mining/source_text.py 58-59,162-174,177-202; mining/orchestrator.py _read_source и _collect_specs_for_file.

Валидный Kubernetes Secret YAML с kind : Secret или data : не совпадает с regex, требующей colon непосредственно после key. При стандартном force_include=False decode_source возвращает skip_reason=None и полный credential-bearing текст. Оркестратор использует skip_reason для остановки до chunking; эти варианты не останавливаются на этом guard. Это обход заявленной Secret exclusion, не намеренный --include-ignored.

## Доказательство

checks/mempalace_secret_yaml.py исполнен на actual frozen owner. PyYAML 6.0.3 подтверждает семантическую эквивалентность canonical, spaced kind, spaced data, both spaced. Canonical skip_reason=secret; все spaced варианты skip_reason=None и текст сохранён. Fixtures содержат только демонстрационное значение. Реальный секрет, palace, LanceDB и полный mine не использовались; фактическая утечка пользовательских credentials не утверждается.

```sh
python3 checks/mempalace_secret_yaml.py --source .raw/mempalace-2026-10-02/git-source
```

## Приёмка

Semantically equivalent Secret manifests с whitespace перед key colon отфильтрованы стандартным mine до записи drawer. Проверить kind, data и stringData; сохранять существующие YAML document boundaries, CRLF/CR handling, не блокировать ConfigMap и сохранить явный force_include exception. Тест валидности должен опираться на YAML parser, отдельно от detector regex. Исправлять существующий source_text owner; новую policy/service boundary не создавать.

Перед backlog intake проверить актуальные source_text/scanner callers и дубликаты; подтверждение относится к snapshot. Product code этим аудитом не изменён.
