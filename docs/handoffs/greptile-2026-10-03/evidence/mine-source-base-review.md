# Mining source: Base после отказа Plus

Plus POST был отклонён HTTP 403 error=trial_limit_reached, run ID отсутствует. Один отдельный Base POST с новой correlationId на тех же пяти целях принят. Это доказывает доступность дешёвого режима для данного остатка; фактический счётчик не запрашивался.

Base run audit-id-withheld COMPLETED, billableCredits=1. Время 22:31:54.919Z — 22:35:42.115Z (227.196 секунды), 2 октября UTC. Frozen 7c8a506a2401cd2eaad474e8d3499055af27ab06; base 3594fbce1050bd0471a3e3b40ed6ebe72473a440.

Coverage self-report FULLY_READ: scanner.py 1-360/361-667; source_text.py 1-202; source_io.py 1-219; tests/test_regular_source_guard.py 1-360/361-710/711-1034; tests/test_mine_source_exact.py 1-166. Всего 2288 строк. Tool trace отсутствует; supporting chunker diff остался truncated и полностью не проверен. refs supplied SHA недоступны в engine environment; провайдер использовал materialized HEAD 285ac0e/base 3594fbc. reviewedBaseSha совпал; независимая проверка actual source owner подтвердила regex/code claim.

Единственная находка: MP-MINE-K8S-SECRET-SPACING P1, confirmed. Валидные spaced key-colon YAML variants обходят Secret guard. Проверка использует actual decode_source и независимый PyYAML semantic comparison; canonical/ConfigMap/force_include controls корректны. Приватные данные и полный mine не запускались. Handoff findings/MP-MINE-K8S-SECRET-SPACING.md.

## Вывод для подхода

Для small connected scope Base тоже дал пять явных full-read rows и воспроизводимую находку. Сравнение с Plus не изолированное: цели разные, поэтому эквивалентное качество моделей не доказано. Для следующего малого контура выбрать Base как дешёвый пилот; повышать effort только по наблюдаемой недостаточности или конкретной сложности. Первый дорогой quota refusal не доказывает исчерпание дешёвого режима. Однократная отдельная Base проверка при разрешении использовать остаток допустима; одинаковые POST не повторять.
