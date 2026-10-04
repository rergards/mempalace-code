"""
test_uat_kg_mining.py — KG regressions on the mining path.

Re-mining an unchanged project keeps its KG rows, a deleted file's extracted facts
expire even when a manual drawer still names it, the mine summary reports every
KG fact it derives, and default layer globs match sub-namespaces.
"""

import sqlite3

import pytest
import yaml

from mempalace_code.architecture import DEFAULT_LAYERS, detect_layer
from mempalace_code.knowledge_graph import KnowledgeGraph
from mempalace_code.miner import mine
from mempalace_code.storage import open_store

_BODY = "\n".join(f"    def step_{i}(self):\n        return {i}\n" for i in range(12))

SOURCES = {
    "shop/__init__.py": "",
    "shop/data/__init__.py": "",
    "shop/data/repo.py": f"import sqlalchemy\n\n\nclass UserRepository:\n{_BODY}",
    "shop/services/__init__.py": "",
    "shop/services/users.py": (
        f"from shop.data.repo import UserRepository\n\n\nclass UserService:\n{_BODY}"
    ),
    "shop/web/__init__.py": "",
    "shop/web/controllers.py": (
        f"from shop.services.users import UserService\n\n\nclass SignupController:\n{_BODY}"
    ),
}


@pytest.fixture
def project(tmp_path):
    root = (tmp_path / "shop-project").resolve()
    for rel, text in SOURCES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "mempalace.yaml").write_text(
        yaml.dump({"wing": "shop", "rooms": [{"name": "general", "description": "All"}]}),
        encoding="utf-8",
    )
    return root


def _mine(project, tmp_path, incremental=True):
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    mine(
        str(project),
        str(tmp_path / "palace"),
        kg=kg,
        incremental=incremental,
        skip_optimize=True,
    )
    return kg


def _counts(kg) -> tuple[int, int]:
    conn = sqlite3.connect(kg.db_path)
    try:
        return conn.execute("SELECT COUNT(*), SUM(valid_to IS NULL) FROM triples").fetchone()
    finally:
        conn.close()


def _ids(kg) -> set[str]:
    conn = sqlite3.connect(kg.db_path)
    try:
        return {row[0] for row in conn.execute("SELECT id FROM triples WHERE valid_to IS NULL")}
    finally:
        conn.close()


class TestRemineKeepsKgStable:
    def test_full_remines_of_an_unchanged_project_add_no_rows(self, project, tmp_path):
        kg = _mine(project, tmp_path, incremental=False)
        first = _counts(kg)
        first_ids = _ids(kg)

        _mine(project, tmp_path, incremental=False)
        _mine(project, tmp_path, incremental=False)

        assert _counts(kg) == first
        assert _ids(kg) == first_ids
        facts = kg.query_entity("UserService", as_of="2026-01-01")
        assert len(facts) == len({(f["predicate"], f["object"]) for f in facts})

    def test_editing_one_file_does_not_churn_other_facts(self, project, tmp_path):
        kg = _mine(project, tmp_path, incremental=False)
        before = _counts(kg)

        users = project / "shop/services/users.py"
        users.write_text(users.read_text() + "\n# edited\n", encoding="utf-8")
        _mine(project, tmp_path)

        assert _counts(kg) == before

    def test_removed_type_is_still_expired(self, project, tmp_path):
        kg = _mine(project, tmp_path, incremental=False)
        users = project / "shop/services/users.py"
        users.write_text(users.read_text().replace("UserService", "AccountService"))

        _mine(project, tmp_path)

        current = {
            f["subject"] for f in kg.query_entity("shop", direction="incoming") if f["current"]
        }
        assert "AccountService" in current
        assert "UserService" not in current

    def test_mine_summary_reports_file_and_architecture_facts(self, project, tmp_path, capsys):
        kg = _mine(project, tmp_path, incremental=False)

        out = capsys.readouterr().out
        line = next(line for line in out.splitlines() if ">> Knowledge graph:" in line)
        file_facts = int(line.split("Knowledge graph: ")[1].split(" file facts")[0])
        arch_facts = int(line.split("extracted, ")[1].split(" architecture facts")[0])
        assert file_facts + arch_facts == _counts(kg)[1]
        assert "new, 0 expired" in line


def test_deleted_file_facts_expire_even_when_a_manual_drawer_names_it(project, tmp_path):
    kg = _mine(project, tmp_path, incremental=False)
    controllers = project / "shop/web/controllers.py"
    kg.add_triple("SignupDecision", "tracks", "controllers", source_file=str(controllers))
    store = open_store(str(tmp_path / "palace"), create=False)
    store.add(
        ids=["manual-decision"],
        documents=["DECISION: SignupController will be replaced by the new flow."],
        metadatas=[{"wing": "shop", "room": "decisions", "source_file": str(controllers)}],
    )
    controllers.unlink()

    _mine(project, tmp_path, incremental=False)

    by_file = [
        f
        for f in kg.query_entity("shop.services.users", direction="incoming")
        if f["predicate"] == "depends_on"
    ]
    assert by_file
    assert not any(f["current"] for f in by_file)
    assert kg.query_entity("SignupDecision")[0]["current"] is True
    reopened = open_store(str(tmp_path / "palace"), create=False)
    assert reopened.get(where={"source_file": str(controllers)})["ids"] == ["manual-decision"]


class TestSubNamespaceLayers:
    @pytest.mark.parametrize(
        ("namespace", "layer"),
        [
            ("Shop.Infrastructure.Email", "Infrastructure"),
            ("Shop.Domain.Entities", "Business"),
            ("Shop.Application.Services", "Business"),
            ("Shop.Web.Controllers", "UI"),
        ],
    )
    def test_default_globs_match_sub_namespaces(self, namespace, layer):
        assert detect_layer("Anything", namespace, DEFAULT_LAYERS) == layer

    def test_namespace_beats_suffix_for_a_sub_namespace(self):
        assert detect_layer("IOrderRepository", "Shop.Application.Services", DEFAULT_LAYERS) == (
            "Business"
        )

    def test_exact_namespace_match_wins_over_a_parent_match(self):
        assert detect_layer("Thing", "Shop.Web.Data", DEFAULT_LAYERS) == "Data"

    def test_near_miss_namespace_is_not_matched(self):
        assert detect_layer("Thing", "Shop.Webhooks", DEFAULT_LAYERS) is None


def test_python_module_depends_on_uses_the_dotted_module_name(project, tmp_path):
    kg = _mine(project, tmp_path, incremental=False)

    users = kg.query_entity("shop.services.users", direction="both")

    assert {(f["direction"], f["subject"], f["object"]) for f in users} >= {
        ("outgoing", "shop.services.users", "shop.data.repo"),
        ("incoming", "shop.web.controllers", "shop.services.users"),
    }
    assert kg.query_entity("users") == []


def test_same_named_modules_stay_distinct(tmp_path):
    from mempalace_code.mining.kg_extract import extract_type_relationships

    root = tmp_path / "proj"
    for rel, text in {
        "shop/__init__.py": "",
        "shop/web/__init__.py": "",
        "shop/web/models.py": "import jinja2\n",
        "shop/data/__init__.py": "",
        "shop/data/models.py": "import sqlalchemy\n",
        "scripts/tool.py": "import os\n",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    assert extract_type_relationships(root / "shop/web/models.py") == [
        ("shop.web.models", "depends_on", "jinja2")
    ]
    assert extract_type_relationships(root / "shop/data/models.py") == [
        ("shop.data.models", "depends_on", "sqlalchemy")
    ]
    assert extract_type_relationships(root / "scripts/tool.py") == [("tool", "depends_on", "os")]
    assert extract_type_relationships(root / "shop/web/__init__.py") == []


# ── arch-1: .NET solution wing ─────────────────────────────────────────────


def _dotnet_solution(root):
    projects = ["Shop.Web", "Shop.Data"]
    lines = [
        f'Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "{name}", '
        f'"{name}\\\\{name}.csproj", "{{00000000-0000-0000-0000-00000000000{i}}}"\nEndProject'
        for i, name in enumerate(projects)
    ]
    root.mkdir(parents=True)
    (root / "Shop.sln").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in projects:
        folder = root / name
        folder.mkdir()
        (folder / f"{name}.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>\n",
            encoding="utf-8",
        )
        (folder / "Thing.cs").write_text(
            f"namespace {name};\npublic class Thing {{ }}\n", encoding="utf-8"
        )
    return root


def test_init_saves_the_solution_wing_that_mine_uses(tmp_path, capsys):
    from mempalace_code.room_detector_local import detect_rooms_local

    root = _dotnet_solution(tmp_path / "shopnet")

    detect_rooms_local(str(root), yes=True)
    init_out = capsys.readouterr().out
    mine(str(root), str(tmp_path / "palace"), dry_run=True)
    mine_out = capsys.readouterr().out

    config = yaml.safe_load((root / "mempalace.yaml").read_text())
    assert config["wing"] == "shop"
    assert config["dotnet_structure"] is True
    assert "WING: shop\n" in init_out
    assert "Wing:    shop\n" in mine_out
    assert "Note:" not in mine_out


def test_mine_keeps_an_explicit_yaml_wing_in_a_dotnet_solution(tmp_path, capsys):
    from mempalace_code.mining.projects import resolve_wing_for_project

    root = _dotnet_solution(tmp_path / "shopnet")
    (root / "mempalace.yaml").write_text(
        yaml.dump(
            {
                "wing": "Shop-Net",
                "dotnet_structure": True,
                "rooms": [{"name": "general", "description": "All"}],
            }
        ),
        encoding="utf-8",
    )

    mine(str(root), str(tmp_path / "palace"), dry_run=True)

    out = capsys.readouterr().out
    assert "Wing:    shop_net\n" in out
    assert "Note:" not in out
    assert resolve_wing_for_project(str(root)) == "shop_net"


# ── gap-7: the README customization example keeps every default rule ──────


def test_readme_architecture_example_keeps_the_default_rules():
    from pathlib import Path

    from mempalace_code.architecture import DEFAULT_PATTERNS, load_arch_config

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    section = readme.split("with the `architecture:` block in `mempalace.yaml`", 1)[1]
    block = section.split("```yaml\n", 1)[1].split("```", 1)[0]
    assert "replaces the whole default list" in section.split("```yaml", 1)[0]

    config = load_arch_config(yaml.safe_load(block))

    assert [p["name"] for p in config["patterns"]] == [p["name"] for p in DEFAULT_PATTERNS]
    assert [layer["name"] for layer in config["layers"]] == [
        layer["name"] for layer in DEFAULT_LAYERS
    ]
    audit = next(p for p in config["patterns"] if p["name"] == "Service")
    assert audit["type_names"] == ["AuditHandler"]
