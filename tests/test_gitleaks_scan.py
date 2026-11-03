"""Focused contracts for the small Gitleaks launcher and workflow wiring."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent


def _load_module():
    path = ROOT / "scripts" / "gitleaks_scan.py"
    spec = importlib.util.spec_from_file_location("gitleaks_scan", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gs = _load_module()


def _completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def _write_suppression_inputs(root: Path, ignore_text: str) -> None:
    _write_safe_go_manifest(root)
    (root / ".gitleaks.toml").write_text(
        'title = "test"\n[extend]\nuseDefault = true\n', encoding="utf-8"
    )
    (root / ".gitleaksignore").write_text(ignore_text, encoding="utf-8")


# Safe floors are grounded in the primary advisory records: GO-2026-4945,
# GHSA-mgcc-cww5-fp2q, GO-2026-5506, GO-2026-6505, GO-2026-6860,
# GO-2026-6866, and GO-2026-6443. The otel 1.45.0 floor retains the
# already qualified baseline shared with its SDK.
_SAFE_GO_REQUIREMENTS = {
    "github.com/go-jose/go-jose/v4": "v4.1.6",
    "go.opentelemetry.io/otel": "v1.45.0",
    "go.opentelemetry.io/otel/sdk": "v1.45.0",
    "golang.org/x/net": "v0.62.0",
    "google.golang.org/grpc": "v1.83.2",
}


def _write_safe_go_manifest(root: Path) -> Path:
    path = root / "tools/gitleaks/go.mod"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "module fixture.invalid/scanner\n\ngo 1.27.3\n\n"
        "require github.com/zricethezav/gitleaks/v8 v8.30.1\n\nrequire (\n"
        + "".join(
            f"    {name} {version} // indirect\n" for name, version in _SAFE_GO_REQUIREMENTS.items()
        )
        + ")\n",
        encoding="utf-8",
    )
    return path


def _metadata(**overrides) -> str:
    value = {
        "owner": "security",
        "rationale": "Reviewed synthetic documentation finding.",
        "review_condition": "Remove with the documented example.",
    }
    value.update(overrides)
    return "# gitleaks-ignore-metadata: " + json.dumps(value, separators=(",", ":"))


def _fingerprint(index: int, path: str | None = None) -> str:
    return f"{index:040x}:{path or f'docs/example-{index}.md'}:generic-api-key:{index + 1}"


def test_changed_range_uses_native_redaction_ignore_and_exact_range(tmp_path):
    calls = []

    def run(command, root):
        calls.append((command, root))
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, stdout="a" * 40 + "\n")
        return _completed(command)

    with patch.object(gs, "_run", side_effect=run):
        rc = gs.scan(
            ROOT,
            base_ref="BASE",
            head_ref="HEAD",
            artifact_dir=tmp_path / "report",
        )

    assert rc == 0
    command = calls[-1][0]
    assert command[:2] == ["gitleaks", "git"]
    assert command[command.index("--log-opts") + 1] == "BASE..HEAD"
    assert "--redact=100" in command
    assert command[command.index("--gitleaks-ignore-path") + 1] == ".gitleaksignore"
    assert command[command.index("--report-format") + 1] == "sarif"


def test_every_repository_scan_validates_suppressions_before_invoking_gitleaks(tmp_path):
    _write_suppression_inputs(tmp_path, _fingerprint(1) + "\n")

    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="lacks immediately preceding metadata"):
            gs.scan(tmp_path, artifact_dir=tmp_path / "artifacts")

    run.assert_not_called()
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("ref", ["", "-HEAD", "0" * 40, "HEAD;echo"])
def test_changed_range_rejects_unsafe_refs_before_scanner(tmp_path, ref):
    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="unsafe base ref"):
            gs.scan(ROOT, base_ref=ref, head_ref="HEAD", artifact_dir=tmp_path)
    run.assert_not_called()


def test_full_history_rejects_shallow_checkout_before_scanner(tmp_path):
    with patch.object(
        gs,
        "_run",
        return_value=_completed(["git"], stdout="true\n"),
    ) as run:
        with pytest.raises(ValueError, match="non-shallow"):
            gs.scan(ROOT, artifact_dir=tmp_path)
    assert run.call_count == 1


def test_scanner_failure_returns_bounded_error(tmp_path, capsys):
    def run(command, root):
        if command[:2] == ["git", "rev-parse"]:
            return _completed(command, stdout="false\n")
        return _completed(command, returncode=1, stderr="secret material must not be echoed")

    with patch.object(gs, "_run", side_effect=run):
        assert gs.scan(ROOT, artifact_dir=tmp_path) == 1

    captured = capsys.readouterr()
    assert "scanner exit 1" in captured.err
    assert "secret material" not in captured.err


def test_workflows_run_fixture_after_installer_before_repository_scan():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    history = (ROOT / ".github" / "workflows" / "gitleaks-history.yml").read_text(encoding="utf-8")

    assert "gitleaks_scan.py changed-range" in ci
    assert "gitleaks_scan.py full-history" in publish
    assert "gitleaks_scan.py full-history" in history
    for text in (ci, publish, history):
        assert "validate-baseline" not in text
        installer = text.index("uses: ./.github/actions/gitleaks-gate")
        fixture = text.index("gitleaks_scan.py fixture-smoke")
        scan = text.index(
            "gitleaks_scan.py changed-range" if text is ci else "gitleaks_scan.py full-history"
        )
        assert installer < fixture < scan


def test_native_ignore_file_has_governed_exact_fingerprints():
    gs.validate_baseline(ROOT)

    fingerprints = [
        line
        for line in (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert fingerprints
    assert len(fingerprints) == len(set(fingerprints))


def test_suppression_parser_accepts_any_number_of_reviewed_exact_fingerprints(tmp_path):
    entries = []
    for index in range(1, 5):
        entries.extend([_metadata(owner=f"owner-{index}"), _fingerprint(index)])
    _write_suppression_inputs(tmp_path, "\n".join(entries) + "\n")

    gs.validate_baseline(tmp_path, today=date(2026, 9, 1))


@pytest.mark.parametrize(
    ("ignore_text", "message"),
    [
        (_metadata() + "\n", "orphan suppression metadata"),
        (_fingerprint(1) + "\n", "lacks immediately preceding metadata"),
        (_metadata(owner="") + "\n" + _fingerprint(1) + "\n", "nonempty owner"),
        (
            _metadata(review_condition=None, expiry="2026-08-31") + "\n" + _fingerprint(1) + "\n",
            "expired",
        ),
        (_metadata() + "\n" + "not:a:fingerprint" + "\n", "malformed exact fingerprint"),
        (_metadata() + "\n " + _fingerprint(1) + "\n", "malformed exact fingerprint"),
        (_metadata() + "\n" + _fingerprint(1, "docs/*.md") + "\n", "path must be exact"),
        (
            "\n".join([_metadata(), _fingerprint(1), _metadata(), _fingerprint(1)]) + "\n",
            "duplicate fingerprint",
        ),
    ],
)
def test_suppression_parser_rejects_ungoverned_broad_or_expired_entries(
    tmp_path, ignore_text, message
):
    _write_suppression_inputs(tmp_path, ignore_text)

    with pytest.raises(ValueError, match=message):
        gs.validate_baseline(tmp_path, today=date(2026, 9, 1))


def test_suppression_parser_rejects_duplicate_metadata_fields(tmp_path):
    metadata = (
        '# gitleaks-ignore-metadata: {"owner":"one","owner":"two",'
        '"rationale":"reviewed","review_condition":"remove later"}'
    )
    _write_suppression_inputs(tmp_path, metadata + "\n" + _fingerprint(1) + "\n")

    with pytest.raises(ValueError, match="duplicate suppression metadata field"):
        gs.validate_baseline(tmp_path)


@pytest.mark.parametrize(
    "config_tail",
    [
        "\n[allowlist]\npaths = ['docs/.*']\n",
        "\n[extend]\ndisabledRules = ['generic-api-key']\n",
        "\n[extend]\npath = 'shared.toml'\n",
        "\n[extend]\nurl = 'https://example.invalid/gitleaks.toml'\n",
        "\n[Extend]\nPath = 'shared.toml'\n",
        "\n[[rules]]\nid = 'disabled-rule'\nregex = 'x'\ndisabled = true\n",
    ],
)
def test_gitleaks_config_rejects_any_suppression_capability(tmp_path, config_tail):
    _write_suppression_inputs(tmp_path, _metadata() + "\n" + _fingerprint(1) + "\n")
    (tmp_path / ".gitleaks.toml").write_text('title = "test"\n' + config_tail, encoding="utf-8")

    with pytest.raises(ValueError, match="suppression-capable|disablement|unvalidated"):
        gs.validate_baseline(tmp_path)


def test_fixture_exit_one_succeeds_only_after_all_five_redacted_sarif_classes(tmp_path):
    _write_suppression_inputs(tmp_path, _metadata() + "\n" + _fingerprint(1) + "\n")
    fixture_roots = []

    def run(command, root):
        if command[:2] != ["gitleaks", "git"]:
            return _completed(command)
        fixture_roots.append(root)
        report_path = Path(command[command.index("--report-path") + 1])
        results = [
            {
                "ruleId": rule_id,
                "locations": [
                    {"physicalLocation": {"artifactLocation": {"uri": f"file:///{filename}"}}}
                ],
            }
            for filename, rule_id in gs._FIXTURE_EXPECTATIONS.items()
        ]
        report_path.write_text(json.dumps({"runs": [{"results": results}]}), encoding="utf-8")
        return _completed(command, returncode=1, stderr="complete fixture values stay hidden")

    with patch.object(gs, "_run", side_effect=run):
        assert gs.fixture_smoke(tmp_path) == 0

    assert len(fixture_roots) == 1
    assert not fixture_roots[0].exists()
    assert fixture_roots[0] != ROOT


def test_runtime_fixture_uses_detector_defined_token_alphabets():
    values = gs._fixture_values()
    source = (ROOT / "scripts" / "gitleaks_scan.py").read_text(encoding="utf-8")

    assert re.search(r"ghp_[A-Za-z0-9]{36}", values["github-token.txt"])
    assert re.search(r"AKIA[A-Z2-7]{16}", values["aws-access-key.txt"])
    assert "-----" + "BEGIN PRIVATE KEY" + "-----" not in source
    assert "-----" + "END PRIVATE KEY" + "-----" not in source


def test_fixture_rejects_complete_generated_material_in_sarif_and_cleans_up(tmp_path, capsys):
    _write_suppression_inputs(tmp_path, _metadata() + "\n" + _fingerprint(1) + "\n")
    values = gs._fixture_values()
    leaked_secret = gs._fixture_secret_values(values)[0]
    fixture_roots = []

    def run(command, root):
        if command[:2] != ["gitleaks", "git"]:
            return _completed(command)
        fixture_roots.append(root)
        report_path = Path(command[command.index("--report-path") + 1])
        results = [
            {
                "ruleId": rule_id,
                "locations": [
                    {"physicalLocation": {"artifactLocation": {"uri": f"file:///{filename}"}}}
                ],
            }
            for filename, rule_id in gs._FIXTURE_EXPECTATIONS.items()
        ]
        report_path.write_text(
            json.dumps({"runs": [{"results": results}], "leak": leaked_secret}),
            encoding="utf-8",
        )
        return _completed(command, returncode=1)

    with (
        patch.object(gs, "_fixture_values", return_value=values),
        patch.object(gs, "_run", side_effect=run),
    ):
        assert gs.fixture_smoke(tmp_path) == 1

    captured = capsys.readouterr()
    assert "complete fixture material" in captured.err
    assert leaked_secret not in captured.err
    assert len(captured.err) < 200
    assert len(fixture_roots) == 1
    assert not fixture_roots[0].exists()


def test_fixture_rejects_exit_one_when_sarif_omits_a_required_class(tmp_path, capsys):
    _write_suppression_inputs(tmp_path, _metadata() + "\n" + _fingerprint(1) + "\n")

    def run(command, root):
        if command[:2] != ["gitleaks", "git"]:
            return _completed(command)
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.write_text(json.dumps({"runs": [{"results": []}]}), encoding="utf-8")
        return _completed(command, returncode=1)

    with patch.object(gs, "_run", side_effect=run):
        assert gs.fixture_smoke(tmp_path) == 1

    captured = capsys.readouterr()
    assert "missing classes" in captured.err
    assert len(captured.err) < 300


def test_composite_action_has_no_wrapper_dependency_install():
    action = (ROOT / ".github" / "actions" / "gitleaks-gate" / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "go install" in action
    assert "requirements.txt" not in action
    assert "pip install" not in action


@pytest.mark.parametrize("entry", ["scan", "fixture_smoke"])
@pytest.mark.parametrize("module", list(_SAFE_GO_REQUIREMENTS))
@pytest.mark.parametrize("change", ["drop", "lower"])
def test_unsafe_go_constraint_refuses_before_cached_scanner(tmp_path, entry, module, change):
    _write_suppression_inputs(tmp_path, "")
    manifest = tmp_path / "tools/gitleaks/go.mod"
    line = f"    {module} {_SAFE_GO_REQUIREMENTS[module]} // indirect\n"
    replacement = "" if change == "drop" else f"    {module} v0.0.1 // indirect\n"
    manifest.write_text(manifest.read_text().replace(line, replacement))
    invoke = getattr(gs, entry)
    kwargs = {"artifact_dir": tmp_path / "artifacts"} if entry == "scan" else {}

    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="security floor"):
            invoke(tmp_path, **kwargs)
    run.assert_not_called()
    assert not (tmp_path / "artifacts").exists()


def test_raw_pr20_manifest_refuses_before_cached_scanner(tmp_path):
    _write_suppression_inputs(tmp_path, "")
    (tmp_path / "tools/gitleaks/go.mod").write_text(_RAW_UNSAFE_PR20_GO_MOD)
    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="security floor"):
            gs.scan(tmp_path, artifact_dir=tmp_path / "artifacts")
    run.assert_not_called()


@pytest.mark.parametrize(
    "suffix",
    [
        "replace golang.org/x/net => golang.org/x/net v0.60.0\n",
        "exclude golang.org/x/net v0.62.0\n",
    ],
)
def test_go_resolution_override_refuses_before_cached_scanner(tmp_path, suffix):
    _write_suppression_inputs(tmp_path, "")
    manifest = tmp_path / "tools/gitleaks/go.mod"
    manifest.write_text(manifest.read_text() + suffix)
    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="re-audit"):
            gs.scan(tmp_path, artifact_dir=tmp_path / "artifacts")
    run.assert_not_called()


def test_gitleaks_pin_change_requires_full_graph_reaudit_before_scanner(tmp_path):
    _write_suppression_inputs(tmp_path, "")
    manifest = tmp_path / "tools/gitleaks/go.mod"
    manifest.write_text(manifest.read_text().replace("v8.30.1", "v8.30.2"))
    with patch.object(gs, "_run") as run:
        with pytest.raises(ValueError, match="re-audit"):
            gs.scan(tmp_path, artifact_dir=tmp_path / "artifacts")
    run.assert_not_called()


def test_safe_higher_go_constraint_allows_cached_scanner(tmp_path):
    _write_suppression_inputs(tmp_path, "")
    manifest = tmp_path / "tools/gitleaks/go.mod"
    manifest.write_text(manifest.read_text().replace("v0.62.0", "v0.62.1"))
    with patch.object(
        gs, "_run", side_effect=lambda command, root: _completed(command, stdout="false\n")
    ) as run:
        assert gs.scan(tmp_path, artifact_dir=tmp_path / "artifacts") == 0
    assert run.call_args_list[-1].args[0][:2] == ["gitleaks", "git"]


_RAW_UNSAFE_PR20_GO_MOD = """module github.com/rergards/mempalace-code/tools/gitleaks

go 1.27.3

require github.com/zricethezav/gitleaks/v8 v8.30.1

require (
	dario.cat/mergo v1.0.2 // indirect
	github.com/BobuSumisu/aho-corasick v1.0.3 // indirect
	github.com/Masterminds/goutils v1.1.1 // indirect
	github.com/Masterminds/semver/v3 v3.5.0 // indirect
	github.com/Masterminds/sprig/v3 v3.3.0 // indirect
	github.com/STARRY-S/zip v0.2.3 // indirect
	github.com/andybalholm/brotli v1.2.7 // indirect
	github.com/aymanbagabas/go-osc52/v2 v2.0.1 // indirect
	github.com/bodgit/plumbing v1.3.0 // indirect
	github.com/bodgit/sevenzip v1.6.5 // indirect
	github.com/bodgit/windows v1.0.1 // indirect
	github.com/charmbracelet/colorprofile v0.2.3-0.20250311203215-f60798e515dc // indirect
	github.com/charmbracelet/lipgloss v1.1.0 // indirect
	github.com/charmbracelet/x/ansi v0.8.0 // indirect
	github.com/charmbracelet/x/cellbuf v0.0.13-0.20250311204145-2c3ea96c31dd // indirect
	github.com/charmbracelet/x/term v0.2.1 // indirect
	github.com/dsnet/compress v0.0.2-0.20230904184137-39efe44ab707 // indirect
	github.com/fatih/semgroup v1.3.0 // indirect
	github.com/fsnotify/fsnotify v1.10.1 // indirect
	github.com/gitleaks/go-gitdiff v0.9.1 // indirect
	github.com/go-viper/mapstructure/v2 v2.4.0 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/h2non/filetype v1.1.3 // indirect
	github.com/hashicorp/go-version v1.9.0 // indirect
	github.com/hashicorp/golang-lru/v2 v2.0.7 // indirect
	github.com/huandu/xstrings v1.6.3 // indirect
	github.com/inconshreveable/mousetrap v1.1.0 // indirect
	github.com/klauspost/compress v1.20.3 // indirect
	github.com/klauspost/pgzip v1.3.0 // indirect
	github.com/lucasb-eyer/go-colorful v1.4.1 // indirect
	github.com/mattn/go-colorable v0.1.16 // indirect
	github.com/mattn/go-isatty v0.0.24 // indirect
	github.com/mattn/go-runewidth v0.0.16 // indirect
	github.com/mholt/archives v0.1.5 // indirect
	github.com/mikelolasagasti/xz v1.0.1 // indirect
	github.com/minio/minlz v1.2.3 // indirect
	github.com/mitchellh/copystructure v1.2.0 // indirect
	github.com/mitchellh/reflectwalk v1.0.2 // indirect
	github.com/muesli/termenv v0.16.0 // indirect
	github.com/nwaples/rardecode/v2 v2.4.5 // indirect
	github.com/pelletier/go-toml/v2 v2.4.3 // indirect
	github.com/pierrec/lz4/v4 v4.1.27 // indirect
	github.com/rivo/uniseg v0.4.7 // indirect
	github.com/rs/zerolog v1.35.1 // indirect
	github.com/sagikazarmark/locafero v0.12.0 // indirect
	github.com/shopspring/decimal v1.6.0 // indirect
	github.com/sorairolake/lzip-go v0.3.8 // indirect
	github.com/spf13/afero v1.15.0 // indirect
	github.com/spf13/cast v1.10.0 // indirect
	github.com/spf13/cobra v1.10.2 // indirect
	github.com/spf13/pflag v1.0.10 // indirect
	github.com/spf13/viper v1.21.0 // indirect
	github.com/stangelandcl/ppmd v0.1.1 // indirect
	github.com/subosito/gotenv v1.6.0 // indirect
	github.com/ulikunitz/xz v0.5.17 // indirect
	github.com/wasilibs/go-re2 v1.13.0 // indirect
	github.com/xo/terminfo v0.0.0-20220910002029-abceb7e1c41e // indirect
	go.yaml.in/yaml/v3 v3.0.4 // indirect
	go4.org v0.0.0-20260112195520-a5071408f32f // indirect
	golang.org/x/crypto v0.58.0 // indirect
	golang.org/x/exp v0.0.0-20250218142911-aa4b98e5adaa // indirect
	golang.org/x/sync v0.24.0 // indirect
	golang.org/x/sys v0.49.0 // indirect
	golang.org/x/text v0.43.0 // indirect
	gopkg.in/check.v1 v1.0.0-20190902080502-41f04d3bba15 // indirect
)
"""
