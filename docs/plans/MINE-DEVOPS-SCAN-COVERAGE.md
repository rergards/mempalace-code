---
slug: MINE-DEVOPS-SCAN-COVERAGE
goal: "Add scan_project integration coverage for remaining DevOps file types"
risk: low
risk_note: "Test-only change covering existing language catalog entries and scan_project filtering; no production code planned"
files:
  - path: tests/test_miner.py
    change: "Add focused scan_project tests for Jinja2 templates, config files, .mk files, Containerfile, and Vagrantfile near the existing DevOps scan tests"
acceptance:
  - id: AC-1
    when: "scan_project() scans a temporary project containing templates/site.j2 and templates/app.jinja2"
    then: "the returned relative file list includes both Jinja2 template paths"
  - id: AC-2
    when: "scan_project() scans a temporary project containing nginx.conf, setup.cfg, settings.ini, and notes.unknown"
    then: "the returned relative file list includes the .conf/.cfg/.ini files and excludes notes.unknown"
  - id: AC-3
    when: "scan_project() scans a temporary project containing make/rules.mk"
    then: "the returned relative file list includes make/rules.mk"
  - id: AC-4
    when: "scan_project() scans a temporary project containing an extensionless Containerfile"
    then: "the returned relative file list includes Containerfile via known filename handling"
  - id: AC-5
    when: "scan_project() scans a temporary project containing an extensionless Vagrantfile"
    then: "the returned relative file list includes Vagrantfile via known filename handling"
out_of_scope:
  - "Production changes to mempalace_code/miner.py or mempalace_code/language_catalog.py"
  - "Additional detect_language unit tests; tests/test_lang_detect.py already covers these mappings"
  - "Calling mine(), storage, embeddings, or palace setup"
  - "Changing scan exclusion, gitignore, or skip-directory behavior"
---

## Design Notes

- Place the new tests immediately after `test_scan_project_includes_makefile()` and before `test_scan_project_skips_terraform_dir()` so all DevOps scan integration coverage stays together.
- Add the five backlog-named functions:
  - `test_scan_project_includes_jinja2_files`
  - `test_scan_project_includes_config_files`
  - `test_scan_project_includes_mk_files`
  - `test_scan_project_includes_containerfile`
  - `test_scan_project_includes_vagrantfile`
- Follow the local `tests/test_miner.py` pattern exactly: `tmpdir = tempfile.mkdtemp()`, `try/finally`, `Path(tmpdir).resolve()`, `write_file(...)`, `files = scanned_files(project_root)`, and `shutil.rmtree(tmpdir)`.
- Assert relative paths from `scanned_files()` rather than raw absolute `Path` objects.
- Keep fixture contents minimal because `scan_project()` only needs readable extensions or known filenames for this coverage; do not introduce `mempalace.yaml`, storage, or embedding work.
- Include one unsupported file such as `notes.unknown` in the config-file test and assert it is absent. This keeps the new coverage honest that scan_project is not simply returning every file.
- Suggested focused verification after implementation:
  `python -m pytest tests/test_miner.py -k "scan_project_includes_jinja2_files or scan_project_includes_config_files or scan_project_includes_mk_files or scan_project_includes_containerfile or scan_project_includes_vagrantfile" -q`
- Suggested style checks after implementation:
  `ruff check tests/test_miner.py`
  `ruff format --check tests/test_miner.py`
