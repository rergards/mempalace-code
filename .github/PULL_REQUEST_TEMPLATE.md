## What does this PR do?

## How to test

## Checklist
- [ ] Lint: `ruff check mempalace_code/ tests/ scripts/`
- [ ] Format: `ruff format --check mempalace_code/ tests/ scripts/`
- [ ] Tests: `python -m pytest tests/ -x -q -m "not needs_network"`
- [ ] Public safety: `python scripts/public_safety_scan.py --tracked --staged`
- [ ] Scorecard: `python scripts/quality_scorecard.py --check`
- [ ] No hardcoded private paths or tokens in committed source
