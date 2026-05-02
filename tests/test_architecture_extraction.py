"""
test_architecture_extraction.py — Tests for the architecture extraction pass.

Covers: config parsing, pattern detection, layer detection, type inventory
scanning, KG emission, mining integration, stale-fact invalidation, and
malformed-rule robustness.
"""

import os
import shutil
import tempfile
from pathlib import Path

import yaml

from mempalace_code.architecture import (
    _NS_PROJECT_SENTINEL,
    ARCH_PREDICATES,
    DEFAULT_LAYERS,
    DEFAULT_PATTERNS,
    detect_layer,
    detect_patterns,
    extract_type_inventory,
    load_arch_config,
    namespace_project_source_file,
    run_arch_pass,
)
from mempalace_code.knowledge_graph import KnowledgeGraph

# ── Helpers ───────────────────────────────────────────────────────────────────


def _active_triples(kg):
    conn = kg._conn()
    rows = conn.execute(
        "SELECT subject, predicate, object FROM triples WHERE valid_to IS NULL"
    ).fetchall()
    conn.close()
    return {(r[0], r[1], r[2]) for r in rows}


# ── load_arch_config ──────────────────────────────────────────────────────────


class TestLoadArchConfig:
    def test_no_architecture_key_returns_defaults(self):
        cfg = load_arch_config({"wing": "myapp"})
        assert cfg["enabled"] is True
        assert cfg["patterns"] == list(DEFAULT_PATTERNS)
        assert cfg["layers"] == list(DEFAULT_LAYERS)

    def test_enabled_false(self):
        cfg = load_arch_config({"architecture": {"enabled": False}})
        assert cfg["enabled"] is False

    def test_enabled_non_bool_defaults_true(self):
        cfg = load_arch_config({"architecture": {"enabled": "yes"}})
        assert cfg["enabled"] is True

    def test_custom_patterns_parsed(self):
        raw = {
            "architecture": {
                "patterns": [
                    {"name": "Handler", "suffixes": ["Handler"], "type_names": ["AuditProcessor"]}
                ]
            }
        }
        cfg = load_arch_config(raw)
        assert len(cfg["patterns"]) == 1
        p = cfg["patterns"][0]
        assert p["name"] == "Handler"
        assert p["suffixes"] == ["Handler"]
        assert p["type_names"] == ["AuditProcessor"]

    def test_custom_patterns_replaces_defaults(self):
        raw = {"architecture": {"patterns": [{"name": "Service", "suffixes": ["Service"]}]}}
        cfg = load_arch_config(raw)
        names = [p["name"] for p in cfg["patterns"]]
        assert "Service" in names
        assert "Repository" not in names  # default patterns not merged in

    def test_custom_layers_parsed(self):
        raw = {
            "architecture": {
                "layers": [{"name": "Business", "namespace_globs": ["*.Audit"], "priority": 1}]
            }
        }
        cfg = load_arch_config(raw)
        assert len(cfg["layers"]) == 1
        assert cfg["layers"][0]["name"] == "Business"
        assert cfg["layers"][0]["namespace_globs"] == ["*.Audit"]

    # AC-3: malformed rule entries are silently ignored

    def test_scalar_pattern_list_ignored(self):
        raw = {"architecture": {"patterns": "Service"}}
        cfg = load_arch_config(raw)
        assert cfg["patterns"] == list(DEFAULT_PATTERNS)

    def test_non_dict_pattern_entry_ignored(self):
        raw = {"architecture": {"patterns": ["Service", None, 42]}}
        cfg = load_arch_config(raw)
        # No valid dict entries → falls back to defaults
        assert cfg["patterns"] == list(DEFAULT_PATTERNS)

    def test_pattern_missing_name_ignored(self):
        raw = {
            "architecture": {
                "patterns": [
                    {"suffixes": ["Service"]},  # no name key
                    {"name": "Factory", "suffixes": ["Factory"]},
                ]
            }
        }
        cfg = load_arch_config(raw)
        assert len(cfg["patterns"]) == 1
        assert cfg["patterns"][0]["name"] == "Factory"

    def test_pattern_non_string_name_ignored(self):
        raw = {"architecture": {"patterns": [{"name": 123, "suffixes": ["Service"]}]}}
        cfg = load_arch_config(raw)
        assert cfg["patterns"] == list(DEFAULT_PATTERNS)

    def test_layer_non_list_namespace_globs_ignored(self):
        raw = {
            "architecture": {"layers": [{"name": "UI", "namespace_globs": "*.UI", "priority": 1}]}
        }
        cfg = load_arch_config(raw)
        # namespace_globs is not a list → entry dropped → fallback to defaults
        assert cfg["layers"] == list(DEFAULT_LAYERS)

    def test_non_dict_raw_config(self):
        cfg = load_arch_config(None)
        assert cfg["enabled"] is True
        assert cfg["patterns"] == list(DEFAULT_PATTERNS)

    def test_non_dict_architecture_block(self):
        cfg = load_arch_config({"architecture": "enabled"})
        assert cfg["enabled"] is True
        assert cfg["patterns"] == list(DEFAULT_PATTERNS)


# ── detect_patterns ───────────────────────────────────────────────────────────


class TestDetectPatterns:
    def test_service_suffix(self):
        assert detect_patterns("UserService", DEFAULT_PATTERNS) == ["Service"]

    def test_repository_suffix(self):
        assert detect_patterns("UserRepository", DEFAULT_PATTERNS) == ["Repository"]

    def test_controller_suffix(self):
        assert detect_patterns("UserController", DEFAULT_PATTERNS) == ["Controller"]

    def test_viewmodel_suffix(self):
        assert detect_patterns("MainViewModel", DEFAULT_PATTERNS) == ["ViewModel"]

    def test_vm_suffix(self):
        assert detect_patterns("OrderVM", DEFAULT_PATTERNS) == ["ViewModel"]

    def test_factory_suffix(self):
        assert detect_patterns("OrderFactory", DEFAULT_PATTERNS) == ["Factory"]

    def test_no_match(self):
        assert detect_patterns("AuditHandler", DEFAULT_PATTERNS) == []

    def test_exact_suffix_name_not_matched(self):
        # "Service" alone should not self-match (type_name == suffix)
        assert detect_patterns("Service", DEFAULT_PATTERNS) == []

    # AC-5: multiple pattern facts (non-exclusive)
    def test_multiple_patterns(self):
        patterns = detect_patterns("BillingServiceFactory", DEFAULT_PATTERNS)
        assert "Service" in patterns
        assert "Factory" in patterns

    def test_explicit_type_names_override(self):
        patterns_cfg = [{"name": "Service", "suffixes": [], "type_names": ["AuditHandler"]}]
        result = detect_patterns("AuditHandler", patterns_cfg)
        assert result == ["Service"]

    def test_explicit_type_names_no_suffix_needed(self):
        # AuditHandler has no Service suffix but is in type_names
        patterns_cfg = [
            {"name": "Service", "suffixes": ["Service"], "type_names": ["AuditHandler"]}
        ]
        result = detect_patterns("AuditHandler", patterns_cfg)
        assert "Service" in result

    def test_empty_patterns_list(self):
        assert detect_patterns("UserService", []) == []


# ── detect_layer ─────────────────────────────────────────────────────────────


class TestDetectLayer:
    def test_namespace_glob_ui(self):
        assert detect_layer("SomeClass", "Company.Web", DEFAULT_LAYERS) == "UI"

    def test_namespace_glob_data(self):
        assert detect_layer("SomeClass", "Company.Persistence", DEFAULT_LAYERS) == "Data"

    def test_namespace_glob_business(self):
        assert detect_layer("SomeClass", "Company.Application", DEFAULT_LAYERS) == "Business"

    def test_namespace_glob_infrastructure(self):
        assert (
            detect_layer("SomeClass", "Company.Infrastructure", DEFAULT_LAYERS) == "Infrastructure"
        )

    def test_type_suffix_service_business(self):
        assert detect_layer("UserService", "", DEFAULT_LAYERS) == "Business"

    def test_type_suffix_repository_data(self):
        assert detect_layer("UserRepository", "", DEFAULT_LAYERS) == "Data"

    def test_type_suffix_controller_ui(self):
        assert detect_layer("UserController", "", DEFAULT_LAYERS) == "UI"

    def test_type_suffix_viewmodel_ui(self):
        assert detect_layer("MainViewModel", "", DEFAULT_LAYERS) == "UI"

    def test_no_match(self):
        assert detect_layer("AuditProcessor", "Company.Core", DEFAULT_LAYERS) is None

    # AC-5: namespace glob takes precedence over type suffix
    def test_namespace_wins_over_suffix(self):
        # BillingServiceFactory is under Infrastructure namespace → Infrastructure layer
        # even though "Service" suffix would map to Business
        layer = detect_layer("BillingServiceFactory", "Company.Infrastructure", DEFAULT_LAYERS)
        assert layer == "Infrastructure"

    # AC-5: single layer fact
    def test_returns_single_layer(self):
        layer = detect_layer("BillingServiceFactory", "Company.Infrastructure", DEFAULT_LAYERS)
        assert isinstance(layer, str)

    def test_priority_order(self):
        # UI has priority 1, Business priority 2 — both could match if we had *.Web namespace
        # and Service type suffix. Namespace glob (UI, priority 1) wins.
        layer = detect_layer("FrontendService", "Company.Web", DEFAULT_LAYERS)
        assert layer == "UI"

    def test_custom_layer_config(self):
        layers = [
            {"name": "Audit", "namespace_globs": ["*.Audit"], "priority": 1, "type_suffixes": []}
        ]
        assert detect_layer("AuditHandler", "Company.Audit", layers) == "Audit"


# ── extract_type_inventory ────────────────────────────────────────────────────


class TestExtractTypeInventory:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(str(self.tmpdir))

    def test_cs_class_extracted(self):
        f = self.tmpdir / "UserService.cs"
        f.write_text("namespace Company.Services;\npublic class UserService { }", encoding="utf-8")
        inv = extract_type_inventory([f], self.tmpdir)
        types = [e["type_name"] for e in inv]
        assert "UserService" in types
        ns = next(e["namespace"] for e in inv if e["type_name"] == "UserService")
        assert ns == "Company.Services"

    def test_cs_multiple_types(self):
        f = self.tmpdir / "Types.cs"
        f.write_text(
            "namespace Company.Domain;\n"
            "public class UserEntity { }\n"
            "public interface IUserRepository { }\n",
            encoding="utf-8",
        )
        inv = extract_type_inventory([f], self.tmpdir)
        types = {e["type_name"] for e in inv}
        assert "UserEntity" in types
        assert "IUserRepository" in types

    def test_cs_block_comment_stripped(self):
        f = self.tmpdir / "Example.cs"
        f.write_text(
            "/* class FakeClass {} */\nnamespace Foo;\npublic class RealClass { }", encoding="utf-8"
        )
        inv = extract_type_inventory([f], self.tmpdir)
        types = {e["type_name"] for e in inv}
        assert "RealClass" in types
        assert "FakeClass" not in types

    def test_fs_type_extracted(self):
        f = self.tmpdir / "Domain.fs"
        f.write_text("namespace Company.Domain\ntype UserAggregate = { Id: int }", encoding="utf-8")
        inv = extract_type_inventory([f], self.tmpdir)
        types = {e["type_name"] for e in inv}
        assert "UserAggregate" in types

    def test_vb_class_extracted(self):
        f = self.tmpdir / "UserService.vb"
        f.write_text(
            "Namespace Company.Services\nPublic Class UserService\nEnd Class",
            encoding="utf-8",
        )
        inv = extract_type_inventory([f], self.tmpdir)
        types = {e["type_name"] for e in inv}
        assert "UserService" in types

    def test_py_class_extracted(self):
        pkg = self.tmpdir / "company" / "services"
        pkg.mkdir(parents=True)
        f = pkg / "user_service.py"
        f.write_text("class UserService:\n    pass\n", encoding="utf-8")
        inv = extract_type_inventory([f], self.tmpdir)
        assert any(e["type_name"] == "UserService" for e in inv)
        ns = next(e["namespace"] for e in inv if e["type_name"] == "UserService")
        assert ns == "company.services"

    def test_non_source_file_skipped(self):
        f = self.tmpdir / "README.md"
        f.write_text("# class FakeClass\n", encoding="utf-8")
        inv = extract_type_inventory([f], self.tmpdir)
        assert inv == []

    def test_unreadable_file_skipped(self):
        inv = extract_type_inventory([self.tmpdir / "nonexistent.cs"], self.tmpdir)
        assert inv == []

    def test_lowercase_type_ignored(self):
        f = self.tmpdir / "helpers.cs"
        f.write_text("namespace Foo;\nclass helper { }\npublic class Helper { }", encoding="utf-8")
        inv = extract_type_inventory([f], self.tmpdir)
        types = {e["type_name"] for e in inv}
        assert "Helper" in types
        assert "helper" not in types

    def test_source_file_path_stored(self):
        f = self.tmpdir / "Service.cs"
        f.write_text("namespace A;\npublic class UserService { }", encoding="utf-8")
        inv = extract_type_inventory([f], self.tmpdir)
        assert inv[0]["source_file"] == str(f)


# ── run_arch_pass ─────────────────────────────────────────────────────────────


class TestRunArchPass:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(str(self.tmpdir))

    def _make_kg(self):
        return KnowledgeGraph(db_path=str(self.tmpdir / "kg.sqlite3"))

    def test_is_pattern_emitted(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserService", "namespace": "Company.Domain", "source_file": "a.cs"}
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)
        results = kg.query_entity("Service", direction="incoming")
        subjects = {r["subject"] for r in results if r["predicate"] == "is_pattern"}
        assert "UserService" in subjects

    def test_is_layer_emitted(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserRepository", "namespace": "Company.Data", "source_file": "a.cs"}
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)
        results = kg.query_entity("Data", direction="incoming")
        subjects = {r["subject"] for r in results if r["predicate"] == "is_layer"}
        assert "UserRepository" in subjects

    def test_in_namespace_emitted(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserService", "namespace": "Company.Services", "source_file": "a.cs"}
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)
        results = kg.query_entity("UserService", direction="outgoing")
        ns_facts = [r for r in results if r["predicate"] == "in_namespace"]
        assert any(r["object"] == "Company.Services" for r in ns_facts)

    def test_in_project_emitted(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserService", "namespace": "Company.Services", "source_file": "a.cs"}
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)
        results = kg.query_entity("UserService", direction="outgoing")
        proj_facts = [r for r in results if r["predicate"] == "in_project"]
        assert any(r["object"] == "myapp" for r in proj_facts)

    def test_namespace_in_project_emitted_with_sentinel(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserService", "namespace": "Company.Services", "source_file": "a.cs"}
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)
        conn = kg._conn()
        rows = conn.execute(
            "SELECT source_file FROM triples WHERE subject=? AND predicate='in_project' AND valid_to IS NULL",
            (kg._entity_id("Company.Services"),),
        ).fetchall()
        conn.close()
        assert any(r[0] == namespace_project_source_file("myapp") for r in rows)

    # AC-1: fixture project
    def test_ac1_service_and_data_layer(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserService", "namespace": "Company.App", "source_file": "s.cs"},
            {"type_name": "UserRepository", "namespace": "Company.Data", "source_file": "r.cs"},
            {"type_name": "UserController", "namespace": "Company.Web", "source_file": "c.cs"},
            {"type_name": "MainViewModel", "namespace": "Company.UI", "source_file": "v.cs"},
            {"type_name": "OrderFactory", "namespace": "Company.App", "source_file": "f.cs"},
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)

        svc_hits = kg.query_entity("Service", direction="incoming")
        assert any(
            r["subject"] == "UserService" and r["predicate"] == "is_pattern" for r in svc_hits
        )

        data_hits = kg.query_entity("Data", direction="incoming")
        assert any(
            r["subject"] == "UserRepository" and r["predicate"] == "is_layer" for r in data_hits
        )

    # AC-2: custom config (AuditHandler classified as Service by type_names)
    def test_ac2_custom_type_names_config(self):
        raw_config = {
            "wing": "audit",
            "architecture": {
                "patterns": [
                    {"name": "Service", "suffixes": ["Service"], "type_names": ["AuditHandler"]}
                ],
                "layers": [
                    {
                        "name": "Business",
                        "namespace_globs": ["*.Audit"],
                        "priority": 1,
                        "type_suffixes": [],
                    }
                ],
            },
        }
        kg = self._make_kg()
        inventory = [
            {"type_name": "AuditHandler", "namespace": "Company.Audit", "source_file": "a.cs"}
        ]
        run_arch_pass(inventory, load_arch_config(raw_config), "audit", kg)

        svc_hits = kg.query_entity("Service", direction="incoming")
        assert any(
            r["subject"] == "AuditHandler" and r["predicate"] == "is_pattern" for r in svc_hits
        )

        biz_hits = kg.query_entity("Business", direction="incoming")
        assert any(
            r["subject"] == "AuditHandler" and r["predicate"] == "is_layer" for r in biz_hits
        )

    # AC-5: BillingServiceFactory gets Service + Factory patterns, single Infrastructure layer
    def test_ac5_multiple_patterns_single_layer(self):
        kg = self._make_kg()
        inventory = [
            {
                "type_name": "BillingServiceFactory",
                "namespace": "Company.Infrastructure",
                "source_file": "b.cs",
            }
        ]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)

        active = _active_triples(kg)
        entity_id = kg._entity_id("BillingServiceFactory")
        service_id = kg._entity_id("Service")
        factory_id = kg._entity_id("Factory")
        infra_id = kg._entity_id("Infrastructure")

        assert (entity_id, "is_pattern", service_id) in active
        assert (entity_id, "is_pattern", factory_id) in active

        layer_triples = [(s, p, o) for s, p, o in active if s == entity_id and p == "is_layer"]
        assert len(layer_triples) == 1
        assert layer_triples[0][2] == infra_id

    def test_enabled_false_emits_nothing(self):
        kg = self._make_kg()
        inventory = [
            {"type_name": "UserService", "namespace": "Company.App", "source_file": "s.cs"}
        ]
        cfg = {"enabled": False, "patterns": list(DEFAULT_PATTERNS), "layers": list(DEFAULT_LAYERS)}
        n = run_arch_pass(inventory, cfg, "myapp", kg)
        assert n == 0

    def test_no_namespace_skips_in_namespace(self):
        kg = self._make_kg()
        inventory = [{"type_name": "UserService", "namespace": "", "source_file": "s.cs"}]
        run_arch_pass(inventory, load_arch_config({}), "myapp", kg)
        results = kg.query_entity("UserService", direction="outgoing")
        ns_facts = [r for r in results if r["predicate"] == "in_namespace"]
        assert ns_facts == []


# ── Invalidation (predicates filter) ─────────────────────────────────────────


class TestPredicatesFilter:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(str(self.tmpdir))

    def test_predicate_filter_expires_only_matching(self):
        kg = KnowledgeGraph(db_path=str(self.tmpdir / "kg.sqlite3"))
        kg.add_triple("UserService", "is_pattern", "Service", source_file="a.cs")
        kg.add_triple("UserService", "inherits", "BaseService", source_file="a.cs")

        kg.invalidate_by_source_file("a.cs", predicates=["is_pattern"])

        active = _active_triples(kg)
        svc_id = kg._entity_id("UserService")
        svc_obj = kg._entity_id("Service")
        base_obj = kg._entity_id("BaseService")
        assert (svc_id, "is_pattern", svc_obj) not in active  # expired
        assert (svc_id, "inherits", base_obj) in active  # preserved

    def test_no_predicate_filter_expires_all(self):
        kg = KnowledgeGraph(db_path=str(self.tmpdir / "kg.sqlite3"))
        kg.add_triple("UserService", "is_pattern", "Service", source_file="a.cs")
        kg.add_triple("UserService", "inherits", "BaseService", source_file="a.cs")

        kg.invalidate_by_source_file("a.cs")

        active = _active_triples(kg)
        svc_id = kg._entity_id("UserService")
        svc_obj = kg._entity_id("Service")
        base_obj = kg._entity_id("BaseService")
        assert (svc_id, "is_pattern", svc_obj) not in active
        assert (svc_id, "inherits", base_obj) not in active

    def test_predicate_filter_different_file_not_affected(self):
        kg = KnowledgeGraph(db_path=str(self.tmpdir / "kg.sqlite3"))
        kg.add_triple("UserService", "is_pattern", "Service", source_file="a.cs")
        kg.add_triple("OrderService", "is_pattern", "Service", source_file="b.cs")

        kg.invalidate_by_source_file("a.cs", predicates=["is_pattern"])

        active = _active_triples(kg)
        usr_id = kg._entity_id("UserService")
        ord_id = kg._entity_id("OrderService")
        svc_obj = kg._entity_id("Service")
        assert (usr_id, "is_pattern", svc_obj) not in active  # file a.cs expired
        assert (ord_id, "is_pattern", svc_obj) in active  # file b.cs untouched

    def test_project_prefix_invalidation_respects_path_boundaries(self):
        """AC-5: project-root invalidation honours path boundary; trailing slash and
        symlinked project_path inputs behave identically to the canonical path."""
        import os

        kg = KnowledgeGraph(db_path=str(self.tmpdir / "kg_ac5.sqlite3"))

        # Use real tempdir subdirs so that Path.resolve() is accurate.
        # Build all paths from the resolved root so stored source_file values match
        # what invalidate_arch_by_project_root computes via Path.resolve().
        proj_root = str((self.tmpdir / "proj").resolve())
        sibling = str((self.tmpdir / "proj-other").resolve())
        os.makedirs(proj_root, exist_ok=True)
        os.makedirs(sibling, exist_ok=True)

        proj_file = os.path.join(proj_root, "src", "AlphaService.cs")
        sibling_file = os.path.join(sibling, "BetaService.cs")
        sentinel = namespace_project_source_file("myapp")

        kg.add_triple("AlphaService", "is_pattern", "Service", source_file=proj_file)
        kg.add_triple("AlphaService", "in_namespace", "Pkg", source_file=proj_file)
        kg.add_triple("Pkg", "in_project", "myapp", source_file=sentinel)
        kg.add_triple("BetaService", "is_pattern", "Service", source_file=sibling_file)
        # Non-arch predicate under proj_root must survive
        kg.add_triple("AlphaService", "inherits", "Base", source_file=proj_file)

        kg.invalidate_arch_by_project_root(
            list(ARCH_PREDICATES),
            project_root=proj_root,
            sentinels=[sentinel],
        )

        active = _active_triples(kg)
        alpha_id = kg._entity_id("AlphaService")
        beta_id = kg._entity_id("BetaService")
        svc_id = kg._entity_id("Service")
        pkg_id = kg._entity_id("Pkg")
        myapp_id = kg._entity_id("myapp")
        base_id = kg._entity_id("Base")

        # Arch predicates under proj_root must be expired
        assert (alpha_id, "is_pattern", svc_id) not in active
        assert (alpha_id, "in_namespace", pkg_id) not in active
        assert (pkg_id, "in_project", myapp_id) not in active
        # Sibling-prefix triple must survive (path boundary honoured)
        assert (beta_id, "is_pattern", svc_id) in active
        # Non-arch predicate must survive
        assert (alpha_id, "inherits", base_id) in active

        # --- Trailing-slash variant ---
        kg2 = KnowledgeGraph(db_path=str(self.tmpdir / "kg_ac5_slash.sqlite3"))
        kg2.add_triple("AlphaService", "is_pattern", "Service", source_file=proj_file)
        kg2.add_triple("BetaService", "is_pattern", "Service", source_file=sibling_file)
        kg2.invalidate_arch_by_project_root(
            ["is_pattern"],
            project_root=proj_root + "/",
            sentinels=[],
        )
        active2 = _active_triples(kg2)
        assert (alpha_id, "is_pattern", svc_id) not in active2
        assert (beta_id, "is_pattern", svc_id) in active2

        # --- Symlink variant ---
        sym_path = str(self.tmpdir / "sym_proj")
        os.symlink(proj_root, sym_path)
        kg3 = KnowledgeGraph(db_path=str(self.tmpdir / "kg_ac5_sym.sqlite3"))
        kg3.add_triple("AlphaService", "is_pattern", "Service", source_file=proj_file)
        kg3.add_triple("BetaService", "is_pattern", "Service", source_file=sibling_file)
        kg3.invalidate_arch_by_project_root(
            ["is_pattern"],
            project_root=sym_path,
            sentinels=[],
        )
        active3 = _active_triples(kg3)
        assert (alpha_id, "is_pattern", svc_id) not in active3
        assert (beta_id, "is_pattern", svc_id) in active3

    def test_project_root_with_like_wildcards_does_not_match_siblings(self):
        """Project roots containing SQL LIKE metacharacters (`_`, `%`) must not
        match sibling paths that happen to satisfy the wildcard pattern.

        Regression for HARDEN round 1: an unescaped `LIKE '/tmp/a_b/%'` would
        also match `/tmp/aXb/...` because `_` is treated as a wildcard.
        """
        kg = KnowledgeGraph(db_path=str(self.tmpdir / "kg_wild.sqlite3"))

        # Use real tempdir subdirs so Path.resolve() is accurate. Stored
        # source_file values must use resolved roots to match what
        # invalidate_arch_by_project_root computes via Path.resolve().
        os.makedirs(str(self.tmpdir / "a_b"), exist_ok=True)
        os.makedirs(str(self.tmpdir / "aXb"), exist_ok=True)
        os.makedirs(str(self.tmpdir / "p%t"), exist_ok=True)
        os.makedirs(str(self.tmpdir / "pANYt"), exist_ok=True)
        proj_root_under = str((self.tmpdir / "a_b").resolve())
        proj_root_pct = str((self.tmpdir / "p%t").resolve())

        # These siblings must NOT be matched by the LIKE pattern when escaped.
        # `aXb` would match `a_b` if `_` is treated as a single-char wildcard.
        # `pANYt` would match `p%t` if `%` is treated as multi-char wildcard.
        sibling_under = str((self.tmpdir / "aXb").resolve()) + "/Beta.cs"
        sibling_pct = str((self.tmpdir / "pANYt").resolve()) + "/Gamma.cs"

        proj_file_under = proj_root_under + "/src/Alpha.cs"
        proj_file_pct = proj_root_pct + "/src/Delta.cs"

        kg.add_triple("Alpha", "is_pattern", "Service", source_file=proj_file_under)
        kg.add_triple("Beta", "is_pattern", "Service", source_file=sibling_under)
        kg.add_triple("Delta", "is_pattern", "Service", source_file=proj_file_pct)
        kg.add_triple("Gamma", "is_pattern", "Service", source_file=sibling_pct)

        # Mine `a_b` — only Alpha should expire.
        kg.invalidate_arch_by_project_root(["is_pattern"], project_root=proj_root_under)

        active = _active_triples(kg)
        svc_id = kg._entity_id("Service")
        assert (kg._entity_id("Alpha"), "is_pattern", svc_id) not in active
        assert (kg._entity_id("Beta"), "is_pattern", svc_id) in active, (
            "sibling /tmp/aXb/... must not be expired by LIKE pattern for /tmp/a_b/"
        )
        assert (kg._entity_id("Delta"), "is_pattern", svc_id) in active
        assert (kg._entity_id("Gamma"), "is_pattern", svc_id) in active

        # Now mine `p%t` — only Delta should expire.
        kg.invalidate_arch_by_project_root(["is_pattern"], project_root=proj_root_pct)

        active = _active_triples(kg)
        assert (kg._entity_id("Delta"), "is_pattern", svc_id) not in active
        assert (kg._entity_id("Gamma"), "is_pattern", svc_id) in active, (
            "sibling /tmp/pANYt/... must not be expired by LIKE pattern for /tmp/p%t/"
        )

    def test_all_arch_predicates_selectively_expired(self):
        kg = KnowledgeGraph(db_path=str(self.tmpdir / "kg.sqlite3"))
        kg.add_triple("UserService", "is_pattern", "Service", source_file="a.cs")
        kg.add_triple("UserService", "is_layer", "Business", source_file="a.cs")
        kg.add_triple("UserService", "in_namespace", "Company.App", source_file="a.cs")
        kg.add_triple("UserService", "in_project", "myapp", source_file="a.cs")
        kg.add_triple("UserService", "inherits", "BaseService", source_file="a.cs")

        kg.invalidate_by_source_file("a.cs", predicates=list(ARCH_PREDICATES))

        active = _active_triples(kg)
        svc_id = kg._entity_id("UserService")
        base_obj = kg._entity_id("BaseService")
        assert (svc_id, "inherits", base_obj) in active  # non-arch preserved
        for subj, pred, _ in active:
            if subj == svc_id and pred in ARCH_PREDICATES:
                raise AssertionError(f"Arch predicate {pred!r} was not expired for UserService")


# ── Mining integration (AC-4 stale fact invalidation) ────────────────────────


class TestMiningIntegration:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, rel_path, content):
        p = Path(self.tmpdir) / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def _make_project(self, extra_config=None):
        cfg = {"wing": "test_arch", "rooms": [{"name": "general", "description": "General"}]}
        if extra_config:
            cfg.update(extra_config)
        self._write(
            "mempalace.yaml",
            yaml.dump(cfg, default_flow_style=False),
        )

    def _mine(self, incremental=True):
        from mempalace_code.knowledge_graph import KnowledgeGraph
        from mempalace_code.miner import mine

        kg_path = os.path.join(self.tmpdir, "kg.sqlite3")
        kg = KnowledgeGraph(db_path=kg_path)
        palace_path = os.path.join(self.tmpdir, "palace")
        mine(self.tmpdir, palace_path, kg=kg, incremental=incremental)
        return kg

    # AC-1: basic pattern + layer queryability after mining
    def test_ac1_service_pattern_queryable_after_mine(self):
        self._make_project()
        self._write(
            "src/UserService.cs",
            "namespace Company.Application;\npublic class UserService { }",
        )
        self._write(
            "src/UserRepository.cs",
            "namespace Company.Data;\npublic class UserRepository { }",
        )
        # Minimal .cs content to give the miner something to chunk
        kg = self._mine(incremental=False)

        results = kg.query_entity("Service", direction="incoming")
        assert any(
            r["subject"] == "UserService" and r["predicate"] == "is_pattern" for r in results
        )

        results = kg.query_entity("Data", direction="incoming")
        assert any(
            r["subject"] == "UserRepository" and r["predicate"] == "is_layer" for r in results
        )

    # AC-3: malformed architecture: block in mempalace.yaml → no exception
    def test_ac3_malformed_arch_config_no_exception(self):
        cfg = {
            "wing": "test_arch",
            "rooms": [{"name": "general", "description": "General"}],
            "architecture": {"patterns": "Service"},  # invalid: scalar instead of list
        }
        self._write("mempalace.yaml", yaml.dump(cfg, default_flow_style=False))
        self._write("src/UserService.cs", "namespace A;\npublic class UserService { }")
        kg = self._mine(incremental=False)
        # Should complete without exception; no arch facts from malformed rules
        results = kg.query_entity("Service", direction="incoming")
        # With malformed patterns, defaults are used — Service is still detected
        # The important thing is no exception was raised
        assert isinstance(results, list)

    # Regression: disabling architecture between mines must expire prior arch facts
    def test_disabling_architecture_expires_prior_facts(self):
        # First mine with default (enabled) config produces arch facts.
        self._make_project()
        svc_file = self._write(
            "src/UserService.cs",
            "namespace Company.Application;\npublic class UserService { }",
        )

        kg = self._mine(incremental=False)

        results = kg.query_entity("Service", direction="incoming")
        active_subjects = {r["subject"] for r in results if r["valid_to"] is None}
        assert "UserService" in active_subjects

        # Second mine with architecture.enabled: false must expire the prior facts,
        # so they no longer surface as current.
        cfg = {
            "wing": "test_arch",
            "rooms": [{"name": "general", "description": "General"}],
            "architecture": {"enabled": False},
        }
        self._write("mempalace.yaml", yaml.dump(cfg, default_flow_style=False))
        # Touch the source file so its content is unchanged but config flips.
        svc_file.write_text(svc_file.read_text(encoding="utf-8"), encoding="utf-8")

        kg2 = self._mine(incremental=False)

        results_after = kg2.query_entity("Service", direction="incoming")
        current_subjects = {r["subject"] for r in results_after if r["valid_to"] is None}
        assert "UserService" not in current_subjects

    # ── Multi-wing helpers ────────────────────────────────────────────────

    def _make_wing_dir(self, wing_name, extra_config=None):
        """Create a project subdirectory with its own mempalace.yaml."""
        wing_dir = os.path.join(self.tmpdir, wing_name)
        os.makedirs(wing_dir, exist_ok=True)
        cfg = {"wing": wing_name, "rooms": [{"name": "general", "description": "General"}]}
        if extra_config:
            cfg.update(extra_config)
        (Path(wing_dir) / "mempalace.yaml").write_text(
            yaml.dump(cfg, default_flow_style=False), encoding="utf-8"
        )
        return wing_dir

    def _mine_wing(self, project_dir, kg):
        from mempalace_code.miner import mine

        palace_path = os.path.join(self.tmpdir, "palace")
        mine(project_dir, palace_path, kg=kg, incremental=False)

    def _shared_kg(self):
        from mempalace_code.knowledge_graph import KnowledgeGraph

        return KnowledgeGraph(db_path=os.path.join(self.tmpdir, "kg.sqlite3"))

    # AC-1: sequential single-wing mines must not wipe other wings' arch facts

    def test_sequential_wing_mines_preserve_prior_arch_facts(self):
        kg = self._shared_kg()

        alpha_dir = self._make_wing_dir("alpha_project")
        (Path(alpha_dir) / "AlphaService.cs").write_text(
            "namespace Alpha.App;\npublic class AlphaService { }", encoding="utf-8"
        )
        (Path(alpha_dir) / "AlphaRepository.cs").write_text(
            "namespace Alpha.Data;\npublic class AlphaRepository { }", encoding="utf-8"
        )

        beta_dir = self._make_wing_dir("beta_project")
        (Path(beta_dir) / "BetaService.cs").write_text(
            "namespace Beta.App;\npublic class BetaService { }", encoding="utf-8"
        )
        (Path(beta_dir) / "BetaDataAdapter.cs").write_text(
            "namespace Beta.Data;\npublic class BetaDataAdapter { }", encoding="utf-8"
        )

        self._mine_wing(alpha_dir, kg)
        self._mine_wing(beta_dir, kg)

        svc_hits = kg.query_entity("Service", direction="incoming")
        current_svc = {
            r["subject"] for r in svc_hits if r["current"] and r["predicate"] == "is_pattern"
        }
        assert "AlphaService" in current_svc, "AlphaService must survive beta mine"
        assert "BetaService" in current_svc

        data_hits = kg.query_entity("Data", direction="incoming")
        current_data = {
            r["subject"] for r in data_hits if r["current"] and r["predicate"] == "is_layer"
        }
        assert "AlphaRepository" in current_data, (
            "AlphaRepository layer fact must survive beta mine"
        )

    # AC-2: namespace→project sentinel is scoped per wing

    def test_namespace_project_sentinel_is_scoped_per_wing(self):
        kg = self._shared_kg()

        alpha_dir = self._make_wing_dir("alpha_project")
        (Path(alpha_dir) / "AlphaSharedUtil.cs").write_text(
            "namespace Company.Shared;\npublic class AlphaSharedUtil { }", encoding="utf-8"
        )

        beta_dir = self._make_wing_dir("beta_project")
        (Path(beta_dir) / "BetaSharedUtil.cs").write_text(
            "namespace Company.Shared;\npublic class BetaSharedUtil { }", encoding="utf-8"
        )

        self._mine_wing(alpha_dir, kg)
        self._mine_wing(beta_dir, kg)

        # Both in_project facts for Company.Shared must be current
        ns_facts = kg.query_entity("Company.Shared", direction="outgoing")
        current_projects = {
            r["object"] for r in ns_facts if r["current"] and r["predicate"] == "in_project"
        }
        assert "alpha_project" in current_projects
        assert "beta_project" in current_projects

        # Active sentinel source_file values must be distinct (one per wing)
        conn = kg._conn()
        rows = conn.execute(
            "SELECT DISTINCT source_file FROM triples"
            " WHERE predicate='in_project' AND valid_to IS NULL AND subject=?",
            (kg._entity_id("Company.Shared"),),
        ).fetchall()
        conn.close()
        sentinel_values = {r[0] for r in rows}
        assert namespace_project_source_file("alpha_project") in sentinel_values
        assert namespace_project_source_file("beta_project") in sentinel_values

    # AC-3: disabling architecture on one wing must not expire other wings' arch facts

    def test_disabling_architecture_expires_only_current_wing_facts(self):
        kg = self._shared_kg()

        alpha_dir = self._make_wing_dir("alpha_project")
        (Path(alpha_dir) / "AlphaService.cs").write_text(
            "namespace Pkg;\npublic class AlphaService { }", encoding="utf-8"
        )

        beta_dir = self._make_wing_dir("beta_project")
        (Path(beta_dir) / "BetaService.cs").write_text(
            "namespace Pkg;\npublic class BetaService { }", encoding="utf-8"
        )

        self._mine_wing(alpha_dir, kg)
        self._mine_wing(beta_dir, kg)

        # Re-mine alpha with architecture disabled
        alpha_dir_disabled = self._make_wing_dir(
            "alpha_project",
            extra_config={"architecture": {"enabled": False}},
        )
        # Carry over the source file
        (Path(alpha_dir_disabled) / "AlphaService.cs").write_text(
            "namespace Pkg;\npublic class AlphaService { }", encoding="utf-8"
        )
        self._mine_wing(alpha_dir_disabled, kg)

        svc_hits = kg.query_entity("Service", direction="incoming")
        current_after = {
            r["subject"] for r in svc_hits if r["current"] and r["predicate"] == "is_pattern"
        }
        assert "AlphaService" not in current_after, "Alpha arch facts must be expired"
        assert "BetaService" in current_after, "Beta arch facts must be unaffected"

    # AC-4: deleting a source file in one wing must not expire other wings' arch facts

    def test_deleted_source_expires_current_wing_arch_facts_without_touching_other_wings(self):
        kg = self._shared_kg()

        alpha_dir = self._make_wing_dir("alpha_project")
        alpha_svc = Path(alpha_dir) / "AlphaService.cs"
        alpha_svc.write_text("namespace Pkg;\npublic class AlphaService { }", encoding="utf-8")
        alpha_ctrl = Path(alpha_dir) / "AlphaController.cs"
        alpha_ctrl.write_text("namespace Pkg;\npublic class AlphaController { }", encoding="utf-8")

        beta_dir = self._make_wing_dir("beta_project")
        (Path(beta_dir) / "BetaService.cs").write_text(
            "namespace Pkg;\npublic class BetaService { }", encoding="utf-8"
        )

        self._mine_wing(alpha_dir, kg)
        self._mine_wing(beta_dir, kg)

        # Delete AlphaService.cs and re-mine alpha
        alpha_svc.unlink()
        self._mine_wing(alpha_dir, kg)

        svc_hits = kg.query_entity("Service", direction="incoming")
        current_svc = {
            r["subject"] for r in svc_hits if r["current"] and r["predicate"] == "is_pattern"
        }
        assert "AlphaService" not in current_svc, (
            "AlphaService fact must be gone after file deleted"
        )
        assert "BetaService" in current_svc, "BetaService fact must be unaffected"

        ctrl_hits = kg.query_entity("Controller", direction="incoming")
        current_ctrl = {
            r["subject"] for r in ctrl_hits if r["current"] and r["predicate"] == "is_pattern"
        }
        assert "AlphaController" in current_ctrl, "AlphaController fact must be re-emitted"

    def test_legacy_ns_project_sentinel_expired_for_current_wing_only(self):
        """HARDEN round 1: pre-WING-SCOPE namespace→project rows used a single
        shared sentinel with no wing suffix.  After upgrade, mining a wing must
        retire only that wing's legacy rows; other wings' legacy rows survive
        until those wings are themselves mined.
        """
        kg = self._shared_kg()

        # Seed legacy rows (as if written by a pre-WING-SCOPE release).
        kg.add_triple("Pkg", "in_project", "alpha_project", source_file=_NS_PROJECT_SENTINEL)
        kg.add_triple("Pkg", "in_project", "beta_project", source_file=_NS_PROJECT_SENTINEL)

        # Mine alpha. The legacy row for alpha must be expired.
        alpha_dir = self._make_wing_dir("alpha_project")
        (Path(alpha_dir) / "AlphaService.cs").write_text(
            "namespace Pkg;\npublic class AlphaService { }", encoding="utf-8"
        )
        self._mine_wing(alpha_dir, kg)

        conn = kg._conn()
        rows = conn.execute(
            "SELECT object, valid_to FROM triples WHERE source_file=? AND predicate='in_project'",
            (_NS_PROJECT_SENTINEL,),
        ).fetchall()
        conn.close()

        legacy_state = {obj: valid_to for obj, valid_to in rows}
        assert legacy_state[kg._entity_id("alpha_project")] is not None, (
            "alpha legacy ns_project sentinel row must be expired after alpha mine"
        )
        assert legacy_state[kg._entity_id("beta_project")] is None, (
            "beta legacy ns_project sentinel row must survive until beta is mined"
        )

    # AC-4: stale fact removed when file is replaced
    def test_ac4_stale_fact_invalidated_on_rename(self):
        self._make_project()
        svc_file = Path(self.tmpdir) / "src" / "UserService.cs"
        svc_file.parent.mkdir(parents=True, exist_ok=True)
        svc_file.write_text("namespace A;\npublic class UserService { }", encoding="utf-8")

        kg = self._mine(incremental=False)

        results = kg.query_entity("Service", direction="incoming")
        assert any(r["subject"] == "UserService" for r in results)

        # Replace UserService.cs with UserManager.cs
        svc_file.unlink()
        mgr_file = Path(self.tmpdir) / "src" / "UserManager.cs"
        mgr_file.write_text("namespace A;\npublic class UserManager { }", encoding="utf-8")

        kg2 = self._mine(incremental=False)

        # UserService fact must no longer be current
        results_after = kg2.query_entity("Service", direction="incoming")
        current_subjects = {r["subject"] for r in results_after if r["valid_to"] is None}
        assert "UserService" not in current_subjects

        # UserManager has no Service suffix → no Service pattern fact
        assert "UserManager" not in current_subjects
