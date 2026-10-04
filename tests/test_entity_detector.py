import shutil
import tempfile
from pathlib import Path

from mempalace_code.entity_detector import confirm_entities, detect_entities, scan_for_detection
from mempalace_code.room_detector_local import get_user_approval


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_for_detection_includes_kotlin_sources_when_prose_is_sparse():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        write_file(project_root / "README.md", "# Single prose file\n")
        write_file(project_root / "src" / "App.kt", "class App\n")
        write_file(project_root / "build.gradle.kts", 'plugins { kotlin("jvm") }\n')

        files = scan_for_detection(str(project_root), max_files=10)
        relative_paths = sorted(path.relative_to(project_root).as_posix() for path in files)

        assert "src/App.kt" in relative_paths
        assert "build.gradle.kts" in relative_paths
    finally:
        shutil.rmtree(tmpdir)


def test_detect_entities_classifies_project_from_kotlin_file_references():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        kotlin_file = project_root / "src" / "App.kt"
        write_file(
            kotlin_file,
            (
                "// Mempalace.kt bootstraps the CLI\n"
                "// Mempalace.kt configures the palace path\n"
                "// Mempalace.kt wires mining commands together\n"
                "class App\n"
            ),
        )

        detected = detect_entities([kotlin_file])
        project_names = [entity["name"] for entity in detected["projects"]]

        assert "Mempalace" in project_names
    finally:
        shutil.rmtree(tmpdir)


def test_room_review_reprompts_unknown_choice(monkeypatch, capsys):
    rooms = [{"name": "backend", "description": "Backend", "keywords": ["backend"]}]
    replies = iter(["wat", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(replies))

    confirmed = get_user_approval(rooms)

    assert confirmed == rooms
    assert "Not recognized" in capsys.readouterr().out


def test_entity_confirmation_reprompts_unknown_choice_and_accepts(monkeypatch, capsys):
    detected = {
        "people": [{"name": "Alice", "confidence": 1.0, "signals": ["test"]}],
        "projects": [{"name": "Apollo", "confidence": 1.0, "signals": ["test"]}],
        "uncertain": [],
    }
    replies = iter(["wat", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(replies))

    confirmed = confirm_entities(detected)

    assert confirmed == {"people": ["Alice"], "projects": ["Apollo"]}
    out = capsys.readouterr().out
    assert "Not recognized" in out
    assert "Confirmed:" in out


# ── r1-install-14: the README example classifies both Alice and Bob as people ──

README_MEETING = """# Weekly sync
Alice said the Apollo repo needs a new deploy pipeline. Thanks Bob for the review.
Bob said Apollo deploy is blocked on the staging cluster. Thanks Alice for the fix.
Alice will deploy Apollo on Friday. Bob asked whether Alice checked the Apollo repo.
Thanks Bob, said Alice.
"""


def test_readme_example_keeps_the_direct_address_signal_beyond_three_actions():
    from mempalace_code.entity_detector import classify_entity, score_entity

    lines = README_MEETING.splitlines()
    scores = score_entity("Bob", README_MEETING, lines)

    assert "addressed" in scores["person_signal_types"]
    assert "action" in scores["person_signal_types"]
    result = classify_entity("Bob", 4, scores)
    assert result["type"] == "person"


def test_thanks_is_counted_once_as_direct_address_and_actions_are_labelled():
    from mempalace_code.entity_detector import score_entity

    text = "Thanks Bob. Bob said hi. Bob asked twice."
    scores = score_entity("Bob", text, text.splitlines())

    assert scores["person_signals"] == [
        "'Bob said' action (1x)",
        "'Bob asked' action (1x)",
        "addressed directly (1x)",
    ]
    assert scores["person_score"] == 2 + 2 + 4


def test_single_signal_type_is_not_labelled_pronoun_only():
    from mempalace_code.entity_detector import classify_entity

    scores = {
        "person_score": 12,
        "project_score": 0,
        "person_signals": ["'Zed said' action (3x)", "'Zed asked' action (3x)"],
        "project_signals": [],
    }
    result = classify_entity("Zed", 6, scores)

    assert result["type"] == "uncertain"
    assert result["signals"][-1] == "appears 6x — single person signal type"
