"""Round-2 UAT regressions for project mining (group "mining").

Each test names the UAT issue it pins.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from mempalace_code.cli_invocation import cli_prefix
from mempalace_code.errors import InvalidArgumentError
from mempalace_code.mining import chunkers, orchestrator, projects
from mempalace_code.mining.chunkers import chunk_file
from mempalace_code.mining.languages import detect_language
from mempalace_code.mining.scanner import scan_project
from mempalace_code.mining.symbols import extract_symbol
from mempalace_code.storage import open_store

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


# =============================================================================
# mine-mjs: ES-module / CommonJS / TS-module extensions are JavaScript/TypeScript
# =============================================================================


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("a.mjs", "javascript"),
        ("b.cjs", "javascript"),
        ("c.mts", "typescript"),
        ("d.cts", "typescript"),
    ],
)
def test_module_extensions_are_scanned_and_chunked_structurally(tmp_path, name, language):
    source = _write(
        tmp_path / name,
        "export function alpha() {\n  return 'alpha value for the module test';\n}\n\n"
        "export function beta() {\n  return 'beta value for the module test';\n}\n",
    )
    unsupported: list = []
    files = scan_project(str(tmp_path), unsupported_files=unsupported)

    assert source in files
    assert unsupported == []
    assert detect_language(source) == language
    chunks = chunk_file(source.read_text(), source.suffix, str(source), language=language)
    assert "\n\n".join(chunk["content"] for chunk in chunks) == source.read_text().strip()


# =============================================================================
# r1-wing-1 / gap-1 / mine-wing-validate: one wing rule for --wing, yaml and init
# =============================================================================


def _init_project(root: Path, wing: str = "uat", rooms: list | None = None) -> None:
    config = {"wing": wing, "rooms": rooms or [{"name": "general", "description": "All"}]}
    _write(root / "mempalace.yaml", yaml.safe_dump(config, allow_unicode=True))


def _mine(project: Path, palace: Path, **kwargs) -> dict:
    kwargs.setdefault("skip_optimize", True)
    return orchestrator.mine(str(project), str(palace), **kwargs)


def _wings(palace: Path) -> dict:
    return open_store(str(palace), create=False, read_only=True).count_by("wing")


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "mempalace_code.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ("Other Wing", "other_wing"),
        ("other wing", "other_wing"),
        ("other_wing", "other_wing"),
        ("Foo Bar (v2)!", "foo_bar_v2"),
        ("café", "café"),
        ("Café", "café"),
        ("日本語", "日本語"),
        ("Мой проект (v2)", "мой_проект_v2"),
    ],
)
def test_wing_override_is_normalized_like_the_yaml_wing(override, expected):
    config = {"wing": "from_yaml"}
    assert projects.mine_wing(config, override) == expected
    assert projects.configured_wing({"wing": override}) == expected
    assert projects.mine_wing(config, "") == "from_yaml"
    assert projects.mine_wing(config, None) == "from_yaml"


def test_non_ascii_project_folders_keep_their_own_wing(tmp_path):
    names = ["日本語", "中文项目", "café", "Мой проект (v2)", "éclair"]
    derived = [
        projects.derive_wing_name(str(_write(tmp_path / n / "a.py", "x = 1\n").parent))
        for n in names
    ]
    assert derived == ["日本語", "中文项目", "café", "мой_проект_v2", "éclair"]
    # An all-punctuation name still falls back to the documented default.
    assert projects._normalize_wing_name("!!!") == "project"


def test_new_wing_that_respells_an_existing_wing_is_refused():
    existing = {"other_wing": 3, "Legacy Wing": 2}
    assert projects.settle_mine_wing(existing, "other_wing", "Other Wing") == "other_wing"
    # A --wing that names a wing an older release stored verbatim keeps filing there.
    assert projects.settle_mine_wing(existing, "legacy_wing", "Legacy Wing") == "Legacy Wing"
    # A --wing that exactly names a legacy verbatim wing wins even when its normalized
    # spelling exists too.
    both = {"Other Wing", "other_wing"}
    assert projects.settle_mine_wing(both, "other_wing", "Other Wing") == "Other Wing"
    assert projects.settle_mine_wing(both, "other_wing", "other wing") == "other_wing"
    assert projects.settle_mine_wing(existing, "brand_new", "brand new") == "brand_new"
    with pytest.raises(InvalidArgumentError, match="existing wing 'other_wing'") as refused:
        projects.settle_mine_wing(
            existing, "other-wing", "other-wing", retry_command=lambda w: f"retry --wing {w}"
        )
    assert refused.value.argument == "wing"
    assert "retry --wing other_wing" in str(refused.value)


@pytest.mark.parametrize(
    ("target", "respelling", "yaml_usable"),
    [
        ("Other Wing", "OTHER_WING", False),
        ("Legacy-Wing", "legacy_wing", False),
        ("other_wing", "OTHER_WING", True),
        ("null", "nu-ll", True),
        ("true", "tr-ue", True),
        ("0123", "0-123", True),
        ("yes", "y-es", True),
        ("no", "n-o", True),
        ("123", "1-23", True),
    ],
)
def test_respelling_recovery_only_offers_yaml_that_selects_existing_wing(
    tmp_path, target, respelling, yaml_usable
):
    with pytest.raises(InvalidArgumentError) as refused:
        projects.settle_mine_wing({target}, respelling, None)

    message = str(refused.value)
    assert f"pass --wing {shlex.quote(target)}" in message
    assert projects.settle_mine_wing({target}, "ignored", target) == target
    if yaml_usable:
        suggestion = message.split(" (or set ", 1)[1].split(" in mempalace.yaml)", 1)[0]
        yaml_config = ast.literal_eval(suggestion)
        assert yaml.safe_load(yaml_config) == {"wing": target}
        (tmp_path / "mempalace.yaml").write_text(yaml_config + "\n", encoding="utf-8")
        assert projects.configured_wing(projects.load_config(str(tmp_path))) == target
    else:
        assert "mempalace.yaml)" not in message


def test_mine_files_case_and_spacing_variants_into_one_wing(tmp_path):
    project = tmp_path / "poly"
    _write(project / "a.py", "def alpha():\n    return 'alpha value for the wing test'\n")
    _init_project(project, wing="Foo Bar (v2)!")
    palace = tmp_path / "palace"

    for override in (None, "Foo Bar (v2)!", "foo bar v2", "FOO_BAR_V2"):
        _mine(project, palace, wing_override=override)
    assert set(_wings(palace)) == {"foo_bar_v2"}

    with pytest.raises(InvalidArgumentError, match="existing wing 'foo_bar_v2'"):
        _mine(project, palace, wing_override="foo-bar-v2")
    assert set(_wings(palace)) == {"foo_bar_v2"}


def test_mine_keeps_a_non_ascii_yaml_wing(tmp_path, capsys):
    project = tmp_path / "日本語"
    _write(project / "a.py", "def jp():\n    return 'japanese project content sample'\n")
    _init_project(project, wing="Café")
    palace = tmp_path / "palace"

    _mine(project, palace)

    assert "Wing:    café" in capsys.readouterr().out
    assert set(_wings(palace)) == {"café"}


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--wing", "   "), "wing must not be blank"),
        (("--wing", "a/b"), "must not contain '/'"),
        (("--wing", "tab\there"), "control characters"),
        (("--agent", ""), "agent must not be blank"),
    ],
)
def test_mine_rejects_blank_or_unsafe_wing_and_agent_before_touching_the_palace(
    tmp_path, args, message
):
    project = tmp_path / "proj"
    _write(project / "a.py", "x = 1\n")
    _init_project(project)
    palace = tmp_path / "palace"

    result = _cli(tmp_path, "--palace", str(palace), "mine", str(project), *args)

    assert result.returncode == 2, result.stderr
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not palace.exists()


def test_mine_all_rejects_a_blank_agent(tmp_path):
    result = _cli(
        tmp_path, "--palace", str(tmp_path / "palace"), "mine-all", str(tmp_path), "--agent", " "
    )
    assert result.returncode == 2
    assert "agent must not be blank" in result.stderr


# =============================================================================
# mine-hint-ux: relevant hints, this installation's binary, every removal counted
# =============================================================================


def test_minified_skip_hint_uses_this_install_and_no_byte_cap_advice(tmp_path, capsys):
    project = tmp_path / "proj"
    _write(project / "app.py", "def main():\n    return 'application entry point'\n")
    _write(project / "data" / "min.json", json.dumps(list(range(3000))))
    _init_project(project)
    palace = tmp_path / "palace"

    _mine(project, palace)

    out = capsys.readouterr().out
    hint = next(line for line in out.splitlines() if "To index one anyway" in line)
    prefix = " ".join(shlex.quote(token) for token in cli_prefix())
    assert f"{prefix} --palace {palace} mine" in hint
    assert "max_file_bytes" not in hint
    assert f"Next: {prefix} --palace {palace} search 'what you are looking for'" in out
    assert "<query>" not in out


def test_drawers_of_a_file_that_became_binary_are_counted_as_removed(tmp_path, capsys):
    project = tmp_path / "proj"
    target = _write(project / "tobin.py", "def soon_binary():\n    return 'will become binary'\n")
    _write(project / "keep.py", "def kept():\n    return 'stays as text source'\n")
    _init_project(project)
    palace = tmp_path / "palace"
    _mine(project, palace)
    capsys.readouterr()

    target.write_bytes(bytes(range(256)) * 8)
    stats = _mine(project, palace)

    out = capsys.readouterr().out
    assert stats["stale_drawers_removed"] == 1
    assert stats["stale_files_removed"] == 1
    assert "Stale drawers removed: 1 (1 deleted, excluded or now-skipped file(s))" in out


def test_status_on_a_missing_palace_names_this_palace(tmp_path, capsys):
    palace = tmp_path / "nopalace"
    assert orchestrator.status(str(palace)) is False
    out = capsys.readouterr().out
    assert f"--palace {palace} init <dir>" in out
    assert f"--palace {palace} mine <dir>" in out


def test_mine_names_the_wing_a_project_was_mined_into_before(tmp_path, capsys):
    project = tmp_path / "日本語"
    _write(project / "a.py", "def jp():\n    return 'japanese project content sample'\n")
    _init_project(project, wing="日本語")
    palace = tmp_path / "palace"
    _mine(project, palace)
    capsys.readouterr()

    _init_project(project, wing="café")
    _mine(project, palace)

    out = capsys.readouterr().out
    assert "mined before into wing '日本語'" in out
    assert set(_wings(palace)) == {"日本語", "café"}


# =============================================================================
# gap-2 / r1-mine-8 / init-gitignored-room: room routing
# =============================================================================

_FOLDER_ROOMS = [
    {"name": "mempalace", "description": "Files from mempalace/", "keywords": ["mempalace"]},
    {"name": "моды", "description": "Files from моды/", "keywords": ["моды"]},
    {"name": "acme_web", "description": "Files from Acme.Web/", "keywords": ["acme_web"]},
    {"name": "acme_data", "description": "Files from Acme.Data/", "keywords": ["acme_data"]},
    {"name": "general", "description": "Files that don't fit other rooms", "keywords": []},
]


def test_non_ascii_folder_room_receives_its_files(tmp_path):
    path = tmp_path / "моды" / "модуль.py"
    assert projects.detect_room(path, "x = 1\n", _FOLDER_ROOMS, tmp_path) == "моды"
    assert projects._tokenize("Моды/Модуль_v2") == ["моды", "модуль", "v2"]


def test_folder_rooms_do_not_claim_root_files_by_content(tmp_path):
    readme = "# mempalace\n\nmempalace is great. Use mempalace to remember.\n"
    assert (
        projects.detect_room(tmp_path / "README.md", readme, _FOLDER_ROOMS, tmp_path) == "general"
    )
    assert (
        projects.detect_room(
            tmp_path / "pyproject.toml", 'name = "mempalace"\n', _FOLDER_ROOMS, tmp_path
        )
        == "general"
    )
    inner = tmp_path / "mempalace" / "core.py"
    assert projects.detect_room(inner, "x = 1\n", _FOLDER_ROOMS, tmp_path) == "mempalace"


def test_folder_rooms_take_only_files_inside_their_folders(tmp_path):
    rooms = [
        *_FOLDER_ROOMS[:-1],
        {"name": "testing", "description": "Files from tests/", "keywords": ["testing", "tests"]},
        {"name": "frontend", "description": "UI code", "keywords": ["components"]},
        _FOLDER_ROOMS[-1],
    ]

    def room(rel: str) -> str:
        return projects.detect_room(tmp_path / rel, "x = 1\n", rooms, tmp_path)

    # File names and partial folder names no longer claim a folder room.
    assert room("mempalace_notes.md") == "general"
    assert room("mempalace.md") == "general"
    assert room("docs/mempalace-design.md") == "general"
    assert room("tests.md") == "general"
    assert room("archive/mempalace_old/x.py") == "general"
    # A folder named exactly like the room or a keyword still routes there.
    assert room("mempalace/core.py") == "mempalace"
    assert room("tests/test_core.py") == "testing"
    assert room("pkg/tests/test_core.py") == "testing"
    assert room("src/Acme.Web/Startup.cs") == "acme_web"
    # Rooms that do not stand for a folder keep partial and file-name matches.
    assert room("ui_components/button.tsx") == "frontend"
    assert room("components.md") == "frontend"


def test_a_content_score_tie_goes_to_general(tmp_path):
    rooms = [
        {"name": "web", "description": "Web code", "keywords": ["acme_web"]},
        {"name": "data", "description": "Data code", "keywords": ["acme_data"]},
    ]
    sln = 'Project("{X}") = "Acme.Web"\nProject("{X}") = "Acme.Data"\n'
    assert projects.detect_room(tmp_path / "Acme.sln", sln, rooms, tmp_path) == "general"
    assert projects.detect_room(tmp_path / "x.txt", "Acme.Web Acme.Web", rooms, tmp_path) == "web"


def test_routing_rule_changes_re_route_unchanged_files(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _write(project / "README.md", "# mempalace\n\nmempalace mempalace mempalace notes here\n")
    _write(project / "mempalace" / "core.py", "def core():\n    return 'core of the package'\n")
    _init_project(project, rooms=_FOLDER_ROOMS)
    palace = tmp_path / "palace"
    rules, is_folder_room = orchestrator.ROOM_ROUTING_RULES, projects._is_folder_room
    # Emulate the previous rules, under which folder rooms were content-scored.
    monkeypatch.setattr(orchestrator, "ROOM_ROUTING_RULES", rules - 1)
    monkeypatch.setattr(projects, "_is_folder_room", lambda room: False)
    _mine(project, palace)
    rows = open_store(str(palace), create=False, read_only=True).count_by_pair("wing", "room")
    assert rows["uat"].get("mempalace") == 2

    monkeypatch.setattr(orchestrator, "ROOM_ROUTING_RULES", rules)
    monkeypatch.setattr(projects, "_is_folder_room", is_folder_room)
    _mine(project, palace)
    rows = open_store(str(palace), create=False, read_only=True).count_by_pair("wing", "room")
    assert rows["uat"] == {"mempalace": 1, "general": 1}


def test_init_does_not_propose_rooms_for_gitignored_directories(tmp_path):
    from mempalace_code.room_detector_local import detect_rooms_from_folders

    _write(tmp_path / ".gitignore", "secret_notes/\nbuild_out/\n")
    _write(tmp_path / "secret_notes" / "plan.md", "BLUEHERON plan\n")
    _write(tmp_path / "backend" / "api.py", "x = 1\n")
    _write(tmp_path / "backend" / "private" / "keys.py", "x = 1\n")
    _write(tmp_path / "backend" / ".gitignore", "private/\n")

    names = {room["name"] for room in detect_rooms_from_folders(str(tmp_path))}

    assert "backend" in names
    assert "secret_notes" not in names
    assert "private" not in names


# =============================================================================
# r1-agent-4 / r1-mine-15: every definition is found by its own symbol_name
# =============================================================================

_FILLER = "".join(
    f"        step_{i} = 'representative body text for the method {i}'\n" for i in range(40)
)
_PY_MODULE = (
    "import os\n\n\n"
    "def tiny_one():\n    return 1\n\n\n"
    "def tiny_two():\n    return 2\n\n\n"
    "class Store:\n"
    '    """A large class that must be split at its methods, not inside them."""\n\n'
    "    limit = 3\n\n"
    "    def __init__(self, path):\n        self.path = path\n\n"
    "    @property\n    def optimize_after_mine(self):\n        return True\n\n"
    "    def count_by(self, field):\n" + _FILLER + "        return {}\n\n"
    "    def count_by_pair(self, a, b):\n" + _FILLER + "        return {}\n\n"
    "    def get_source_files(self):\n"
    '        """Return every stored source file."""\n' + _FILLER + "        return []\n\n"
    "    def total_footprint_bytes(self):\n        return 0\n\n\n"
    "def outer():\n    def nested_helper():\n        return 1\n    return nested_helper()\n"
)


def _labels(content: str, ext: str, language: str) -> list[tuple[str, str, dict]]:
    labelled = []
    for chunk in chunk_file(content, ext, f"f{ext}", language=language):
        name, kind = chunk.get("symbol_name"), chunk.get("symbol_type")
        if name is None or kind is None:
            name, kind = extract_symbol(chunk["content"], language)
        labelled.append((name, kind, chunk))
    return labelled


@pytest.fixture(params=["treesitter", "regex"])
def chunker_path(request, monkeypatch):
    if request.param == "regex":
        monkeypatch.setattr(chunkers, "get_parser", lambda _language: None)
    elif chunkers.get_parser("python") is None:
        pytest.skip("tree-sitter not installed")
    return request.param


def test_every_top_level_and_member_definition_names_its_own_chunk(chunker_path):
    labelled = _labels(_PY_MODULE, ".py", "python")
    names = {name: (kind, chunk) for name, kind, chunk in labelled}

    for expected in (
        "tiny_one",
        "tiny_two",
        "Store",
        "__init__",
        "optimize_after_mine",
        "count_by",
        "count_by_pair",
        "get_source_files",
        "total_footprint_bytes",
        "outer",
    ):
        assert expected in names, (chunker_path, expected, [n for n, _k, _c in labelled])
    assert names["get_source_files"][0] == "method"
    assert names["tiny_one"][0] == "function"
    assert names["Store"][0] == "class"
    # A method's drawer starts at its def (decorators included), never mid-body.
    assert names["optimize_after_mine"][1]["content"].lstrip().startswith("@property")
    for name, _kind, chunk in labelled:
        if name == "get_source_files" and not chunk.get("continuation"):
            assert chunk["content"].lstrip().startswith("def get_source_files")
    # Verbatim-first: the chunks still partition the file's non-blank lines.
    lines = _PY_MODULE.split("\n")
    covered = sorted(n for _n, _k, c in labelled for n in range(c["line_start"], c["line_end"] + 1))
    assert covered == sorted(set(covered))
    assert {n for n, line in enumerate(lines, 1) if line.strip()} <= set(covered)


def test_rust_indented_method_is_named_after_itself(chunker_path):
    rust = (
        "impl LruCache {\n"
        "    pub fn put(&mut self, key: String) {\n        self.map.insert(key, 1);\n    }\n"
        "}\n\n"
        "pub fn evict_expired_entries(cache: &mut LruCache) {}\n"
    )
    labelled = [(name, kind) for name, kind, _chunk in _labels(rust, ".rs", "rust")]
    assert ("put", "method") in labelled
    assert ("evict_expired_entries", "function") in labelled
    assert extract_symbol("    pub fn put(&mut self) {}\n", "rust") == ("put", "method")


def test_typescript_class_methods_are_named_with_tree_sitter():
    if chunkers.get_parser("typescript") is None:
        pytest.skip("tree-sitter not installed")
    ts = (
        "export class Cache {\n  size = 0;\n  put(key: string) { return key }\n"
        "  static create() { return new Cache() }\n}\n"
        "export const handler = (req: string) => req;\n"
    )
    labelled = [(name, kind) for name, kind, _chunk in _labels(ts, ".ts", "typescript")]
    assert labelled[:3] == [("Cache", "class"), ("put", "method"), ("create", "method")]
    assert ("handler", "function") in labelled


def test_per_symbol_chunkers_are_new_regenerable_strategies():
    from mempalace_code import storage

    assert chunkers.STRATEGY_TREESITTER == "treesitter_v3"
    assert chunkers.STRATEGY_REGEX_STRUCTURAL == "regex_structural_v3"
    assert set(storage._FILE_MINING_CHUNKER_STRATEGIES) >= chunkers.FILE_CHUNKER_STRATEGIES
    assert "treesitter_v2" not in chunkers.FILE_CHUNKER_STRATEGIES


def test_code_search_symbol_name_finds_a_method_of_a_large_class(tmp_path):
    from mempalace_code.searcher import code_search

    project = tmp_path / "proj"
    _write(project / "store.py", _PY_MODULE)
    _init_project(project)
    palace = tmp_path / "palace"
    _mine(project, palace)

    for name in ("get_source_files", "optimize_after_mine", "total_footprint_bytes", "tiny_two"):
        hits = code_search(str(palace), name, symbol_name=name, n_results=5)["results"]
        assert hits, name
        assert {hit["symbol_name"] for hit in hits} == {name}


def test_ctrl_c_during_embedding_does_not_embed_the_batch_again(tmp_path, monkeypatch, capsys):
    project = tmp_path / "proj"
    for index in range(3):
        _write(project / f"m{index}.py", f"def f{index}():\n    return 'module {index} body'\n")
    _init_project(project)
    palace = tmp_path / "palace"
    monkeypatch.setattr(orchestrator, "get_batch_size", lambda: 2)
    calls = {"n": 0}

    def interrupted_embedding(collection, specs, **kwargs):
        calls["n"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator, "add_drawers_batch", interrupted_embedding)

    with pytest.raises(KeyboardInterrupt):
        _mine(project, palace)

    out = capsys.readouterr().out
    assert calls["n"] == 1
    assert "Interrupted while embedding batch 1; its 2 chunks may not have been filed" in out
    assert "stay out of search until the next mine" in out
    assert "Embedding batch 2" not in out
    assert "rerun to finish" in out


# =============================================================================
# gap-6: Kubernetes Secret manifests are not stored verbatim by default
# =============================================================================


def test_kubernetes_secret_manifests_are_skipped_and_reported(tmp_path, capsys):
    project = tmp_path / "secrets"
    secret = _write(
        project / "k8s" / "db-secret.yaml",
        "apiVersion: v1\nkind: Secret\nmetadata:\n  name: db\n"
        "stringData:\n  password: Sup3rS3cret\n",
    )
    _write(
        project / "k8s" / "cm.yaml",
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: app\ndata:\n  mode: prod\n",
    )
    _init_project(project)
    palace = tmp_path / "palace"

    stats = _mine(project, palace)

    out = capsys.readouterr().out
    assert stats["files_skipped_by_reason"] == {"secret": 1}
    assert "Files skipped (Kubernetes Secret manifest): 1" in out
    assert "--include-ignored k8s/db-secret.yaml" in out
    store = open_store(str(palace), create=False, read_only=True)
    documents = [row["text"] for batch in store.iter_all() for row in batch]
    assert not any("Sup3rS3cret" in document for document in documents)

    _mine(project, palace, include_ignored=["k8s/db-secret.yaml"])
    documents = [row["text"] for batch in store.iter_all() for row in batch]
    assert any("Sup3rS3cret" in document for document in documents)
    assert str(secret) in {row["source_file"] for batch in store.iter_all() for row in batch}


def test_k8s_secret_detection_checks_each_yaml_document():
    from mempalace_code.mining.source_text import looks_like_k8s_secret

    secret_without_data = "kind: Secret\nmetadata:\n  name: empty\n"
    config_map = "kind: ConfigMap\ndata:\n  mode: fast\n"
    assert not looks_like_k8s_secret("app.yaml", f"{secret_without_data}---\n{config_map}")
    secret = "kind: Secret\ndata:\n  pw: c2VjcmV0\n"
    assert looks_like_k8s_secret("app.yaml", f"{config_map}---\n{secret}")
    assert looks_like_k8s_secret("app.yml", secret)
    assert not looks_like_k8s_secret("app.txt", secret)


def test_k8s_secret_with_crlf_line_endings_is_detected():
    from mempalace_code.mining.source_text import looks_like_k8s_secret

    manifest = "apiVersion: v1\r\nkind: Secret\r\nmetadata:\r\n  name: db\r\ndata:\r\n  password: cGFzcw==\r\n"
    assert looks_like_k8s_secret("secret.yaml", manifest)
    assert looks_like_k8s_secret("secret.yaml", manifest.replace("\r\n", "\r"))
    assert not looks_like_k8s_secret(
        "cm.yaml", "kind: ConfigMap\r\ndata:\r\n  a: b\r\n---\r\nkind: Secret\r\n"
    )
