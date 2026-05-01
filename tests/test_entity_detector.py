import shutil
import tempfile
from pathlib import Path

from mempalace_code.entity_detector import detect_entities, scan_for_detection


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
