"""
test_installed_cli_palace_scope.py — CLI-level palace scope tests (AC-6).

Verifies that the CLI command handlers (backup, mine, export, import) correctly
compute and pass the palace-local KG path when --palace is explicit, and that
they fall back to None (global default) when --palace is absent.

These are unit-level tests on the CLI command handler functions — not subprocess tests.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

from mempalace_code.knowledge_graph import palace_kg_path

# ─── cmd_backup_create KG scoping ──────────────────────────────────────────────


class TestCmdBackupCreateKgScope:
    def _make_args(self, palace: str | None, out: str | None = None, kind: str = "manual"):
        return SimpleNamespace(palace=palace, out=out, kind=kind)

    def test_explicit_palace_uses_local_kg(self, tmp_dir):
        """cmd_backup_create with --palace must pass palace_kg_path to create_backup."""
        palace_path = os.path.join(tmp_dir, "palace")
        expected_kg = palace_kg_path(palace_path)

        captured = {}

        def fake_create_backup(pp, out_path=None, kind="manual", kg_path=None, **kw):
            captured["kg_path"] = kg_path
            captured["palace_path"] = pp
            archive = os.path.join(tmp_dir, "backup.tar.gz")
            with open(archive, "wb") as f:
                f.write(b"")
            return {"drawer_count": 0, "wings": []}, archive

        with patch("mempalace_code.backup.create_backup", side_effect=fake_create_backup):
            from mempalace_code.cli_commands.backup_restore import cmd_backup_create

            cmd_backup_create(self._make_args(palace=palace_path))

        assert "kg_path" in captured, "create_backup must be called"
        assert captured["kg_path"] == expected_kg, (
            f"CLI must pass palace-local kg_path={expected_kg!r}, got: {captured['kg_path']!r}"
        )

    def test_no_palace_flag_uses_global_kg(self, tmp_dir):
        """cmd_backup_create without --palace must not pass a scoped kg_path (None → global default)."""
        captured = {}

        def fake_create_backup(pp, out_path=None, kind="manual", kg_path=None, **kw):
            captured["kg_path"] = kg_path
            archive = os.path.join(tmp_dir, "backup.tar.gz")
            with open(archive, "wb") as f:
                f.write(b"")
            return {"drawer_count": 0, "wings": []}, archive

        with (
            patch("mempalace_code.backup.create_backup", side_effect=fake_create_backup),
            patch("mempalace_code.cli_commands.backup_restore.MempalaceConfig") as MockConfig,
        ):
            MockConfig.return_value.palace_path = os.path.join(tmp_dir, "default_palace")
            from mempalace_code.cli_commands.backup_restore import cmd_backup_create

            cmd_backup_create(self._make_args(palace=None))

        assert "kg_path" in captured
        assert captured["kg_path"] is None, (
            f"Without --palace, kg_path must be None (let backup use global default), "
            f"got: {captured['kg_path']!r}"
        )

    def test_explicit_palace_kg_path_is_inside_palace(self, tmp_dir):
        """The scoped kg_path must be a subpath of the palace directory."""
        palace_path = os.path.join(tmp_dir, "my_palace")
        captured = {}

        def fake_create_backup(pp, out_path=None, kind="manual", kg_path=None, **kw):
            captured["kg_path"] = kg_path
            captured["palace_path"] = pp
            archive = os.path.join(tmp_dir, "b.tar.gz")
            with open(archive, "wb") as f:
                f.write(b"")
            return {"drawer_count": 0, "wings": []}, archive

        with patch("mempalace_code.backup.create_backup", side_effect=fake_create_backup):
            from mempalace_code.cli_commands.backup_restore import cmd_backup_create

            cmd_backup_create(self._make_args(palace=palace_path))

        kg = captured.get("kg_path", "")
        assert kg, f"scoped kg_path must be inside palace dir {palace_path!r}, got: {kg!r}"
        assert kg.startswith(palace_path), (
            f"scoped kg_path must be inside palace dir {palace_path!r}, got: {kg!r}"
        )


# ─── cmd_mine KG scoping ───────────────────────────────────────────────────────


class TestCmdMineKgScope:
    def _make_args(
        self,
        palace: str | None,
        project_dir: str = ".",
        *,
        full: bool = False,
        dry_run: bool = False,
        wing: str | None = None,
        agent: str = "mempalace",
        limit: int = 0,
        no_gitignore: bool = False,
        include_ignored: str | None = None,
        mode: str = "code",
        spellcheck: bool | None = None,
        watch: bool = False,
        extract: str | None = None,
        include_emotional: bool = False,
    ):
        return SimpleNamespace(
            palace=palace,
            dir=project_dir,
            full=full,
            dry_run=dry_run,
            wing=wing,
            agent=agent,
            limit=limit,
            no_gitignore=no_gitignore,
            include_ignored=include_ignored,
            mode=mode,
            spellcheck=spellcheck,
            watch=watch,
            extract=extract,
            include_emotional=include_emotional,
        )

    def test_explicit_palace_uses_lazy_kg_with_local_path(self, tmp_dir):
        """cmd_mine with --palace must create a LazyKnowledgeGraph with the palace-local db_path."""
        palace_path = os.path.join(tmp_dir, "palace")
        project_dir = os.path.join(tmp_dir, "project")
        os.makedirs(project_dir)
        expected_kg_path = palace_kg_path(palace_path)

        mine_calls = {}

        def fake_mine(project_dir, palace_path, kg=None, **kw):
            mine_calls["kg_db_path"] = getattr(kg, "_db_path", "not_lazy")
            mine_calls["called"] = True

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            from mempalace_code.cli_commands.ingest import cmd_mine

            cmd_mine(self._make_args(palace=palace_path, project_dir=project_dir))

        assert mine_calls.get("called"), "mine must have been called"
        assert mine_calls["kg_db_path"] == expected_kg_path, (
            f"LazyKG db_path must be {expected_kg_path!r}, got: {mine_calls['kg_db_path']!r}"
        )

    def test_no_palace_flag_uses_lazy_kg_with_none_path(self, tmp_dir):
        """cmd_mine without --palace must create a LazyKnowledgeGraph with db_path=None."""
        project_dir = os.path.join(tmp_dir, "project")
        os.makedirs(project_dir)

        mine_calls = {}

        def fake_mine(project_dir, palace_path, kg=None, **kw):
            mine_calls["kg_db_path"] = getattr(kg, "_db_path", "not_lazy")
            mine_calls["called"] = True

        with (
            patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine),
            patch("mempalace_code.cli_commands.ingest.MempalaceConfig") as MockCfg,
        ):
            MockCfg.return_value.palace_path = os.path.join(tmp_dir, "default_palace")
            from mempalace_code.cli_commands.ingest import cmd_mine

            cmd_mine(self._make_args(palace=None, project_dir=project_dir))

        assert mine_calls.get("called"), "mine must have been called"
        assert mine_calls["kg_db_path"] is None, (
            f"Without --palace, LazyKG db_path must be None, got: {mine_calls['kg_db_path']!r}"
        )


# ─── cmd_mine_all KG scoping ───────────────────────────────────────────────────


class TestCmdMineAllKgScope:
    def _make_args(
        self,
        palace: str | None,
        project_dir: str,
        *,
        dry_run: bool = False,
        new_only: bool = False,
        agent: str = "mempalace",
        no_gitignore: bool = False,
        include_ignored: str | None = None,
    ):
        return SimpleNamespace(
            palace=palace,
            dir=project_dir,
            dry_run=dry_run,
            new_only=new_only,
            agent=agent,
            no_gitignore=no_gitignore,
            include_ignored=include_ignored,
        )

    def test_mine_all_explicit_palace_uses_local_kg(self, tmp_dir):
        """cmd_mine_all with --palace must create LazyKnowledgeGraph with palace-local db_path."""
        palace_path = os.path.join(tmp_dir, "palace")
        parent_dir = os.path.join(tmp_dir, "projects")
        project_a = os.path.join(parent_dir, "alpha")
        os.makedirs(project_a)
        import yaml

        with open(os.path.join(project_a, "mempalace.yaml"), "w") as f:
            yaml.dump({"wing": "alpha", "rooms": []}, f)
        # Add a project marker so detect_projects recognises this directory
        with open(os.path.join(project_a, "pyproject.toml"), "w") as f:
            f.write('[project]\nname = "alpha"\n')

        expected_kg_path = palace_kg_path(palace_path)

        mine_kg_paths = []

        def fake_mine(project_dir, palace_path, kg=None, **kw):
            mine_kg_paths.append(getattr(kg, "_db_path", "not_lazy"))

        with (
            patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine),
            patch("mempalace_code.cli_commands.ingest.MempalaceConfig") as MockCfg,
            patch("mempalace_code.storage.open_store") as MockStore,
        ):
            MockCfg.return_value.palace_path = palace_path
            mock_store_inst = MockStore.return_value
            mock_store_inst.count_by.return_value = {}

            from mempalace_code.cli_commands.ingest import cmd_mine_all

            cmd_mine_all(self._make_args(palace=palace_path, project_dir=parent_dir))

        assert mine_kg_paths, "mine must have been called for at least one project"
        for path in mine_kg_paths:
            assert path == expected_kg_path, (
                f"mine_all must pass palace-local kg_path={expected_kg_path!r}, got: {path!r}"
            )


# ─── cmd_export / cmd_import KG scoping ───────────────────────────────────────


class TestCmdExportImportKgScope:
    def test_export_explicit_palace_uses_local_kg(self, tmp_dir):
        palace_path = os.path.join(tmp_dir, "palace")
        os.makedirs(palace_path)
        args = SimpleNamespace(
            palace=palace_path,
            out="-",
            with_kg=True,
            only_manual=False,
            wing=None,
            room=None,
            since=None,
            with_embeddings=False,
        )

        with (
            patch("mempalace_code.storage.open_store"),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph") as kg_open,
            patch(
                "mempalace_code.export.write_jsonl",
                return_value={"drawer_count": 0, "kg_count": 0},
            ),
        ):
            from mempalace_code.cli_commands.export_import import cmd_export

            cmd_export(args)

        kg_open.assert_called_once_with(db_path=palace_kg_path(palace_path))

    def test_export_omitted_palace_uses_global_kg_default(self, tmp_dir):
        palace_path = os.path.join(tmp_dir, "default-palace")
        os.makedirs(palace_path)
        args = SimpleNamespace(
            palace=None,
            out="-",
            with_kg=True,
            only_manual=False,
            wing=None,
            room=None,
            since=None,
            with_embeddings=False,
        )

        with (
            patch("mempalace_code.storage.open_store"),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph") as kg_open,
            patch(
                "mempalace_code.export.write_jsonl",
                return_value={"drawer_count": 0, "kg_count": 0},
            ),
            patch("mempalace_code.cli_commands.export_import.MempalaceConfig") as config,
        ):
            config.return_value.palace_path = palace_path
            from mempalace_code.cli_commands.export_import import cmd_export

            cmd_export(args)

        kg_open.assert_called_once_with(db_path=None)

    def test_import_explicit_palace_scopes_live_and_dry_run_kg(self, tmp_dir):
        palace_path = os.path.join(tmp_dir, "palace")
        jsonl_path = os.path.join(tmp_dir, "import.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as handle:
            handle.write('{"type": "export_header"}\n')
        args = SimpleNamespace(
            palace=palace_path,
            jsonl_file=jsonl_path,
            dry_run=False,
            skip_kg=False,
            skip_dedup=False,
            wing_override=None,
        )
        expected_path = palace_kg_path(palace_path)

        with (
            patch("mempalace_code.storage.open_store"),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph") as kg_open,
            patch("mempalace_code.knowledge_graph.LazyKnowledgeGraph") as lazy_kg_open,
            patch("mempalace_code.export.read_jsonl", return_value=iter([])),
            patch(
                "mempalace_code.export.import_jsonl",
                return_value={
                    "imported_drawers": 0,
                    "skipped_duplicates": 0,
                    "imported_triples": 0,
                    "warnings": [],
                },
            ),
        ):
            from mempalace_code.cli_commands.export_import import cmd_import

            cmd_import(args)
            args.dry_run = True
            cmd_import(args)

        kg_open.assert_called_once_with(db_path=expected_path)
        lazy_kg_open.assert_called_once_with(db_path=expected_path)

    def test_import_omitted_palace_preserves_global_kg_default(self, tmp_dir):
        palace_path = os.path.join(tmp_dir, "default-palace")
        jsonl_path = os.path.join(tmp_dir, "import.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as handle:
            handle.write('{"type": "export_header"}\n')
        args = SimpleNamespace(
            palace=None,
            jsonl_file=jsonl_path,
            dry_run=False,
            skip_kg=False,
            skip_dedup=False,
            wing_override=None,
        )

        with (
            patch("mempalace_code.storage.open_store"),
            patch("mempalace_code.knowledge_graph.KnowledgeGraph") as kg_open,
            patch("mempalace_code.knowledge_graph.LazyKnowledgeGraph") as lazy_kg_open,
            patch("mempalace_code.export.read_jsonl", return_value=iter([])),
            patch(
                "mempalace_code.export.import_jsonl",
                return_value={
                    "imported_drawers": 0,
                    "skipped_duplicates": 0,
                    "imported_triples": 0,
                    "warnings": [],
                },
            ),
            patch("mempalace_code.cli_commands.export_import.MempalaceConfig") as config,
        ):
            config.return_value.palace_path = palace_path
            from mempalace_code.cli_commands.export_import import cmd_import

            cmd_import(args)
            args.dry_run = True
            cmd_import(args)

        kg_open.assert_called_once_with(db_path=None)
        lazy_kg_open.assert_called_once_with(db_path=None)
