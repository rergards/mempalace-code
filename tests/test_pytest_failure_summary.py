from pathlib import Path

from scripts import pytest_failure_summary as summary


def write_report(path: Path, testcase: str) -> None:
    path.write_text(
        f"<testsuites><testsuite><testcase {testcase}></testcase></testsuite></testsuites>",
        encoding="utf-8",
    )


def test_first_failure_reports_public_base_identifiers(tmp_path):
    report = tmp_path / "pytest.xml"
    write_report(
        report,
        'classname="tests.test_module.TestCase" name="test_value[param%&#10;secret]"'
        '><failure message="mempalace_reason=watcher_rss_peak">'
        "private traceback is never emitted</failure",
    )

    assert summary.first_failure(report) == (
        "tests.test_module.TestCase",
        "test_value",
        "failure",
        "watcher_rss_peak",
    )


def test_first_failure_rejects_non_public_identifiers_and_error_text(tmp_path):
    report = tmp_path / "pytest.xml"
    write_report(
        report,
        'classname="/private/customer" name="secret%&#10;::warning::value"'
        '><error message="mempalace_reason=customer_secret">credential-like-value</error',
    )

    assert summary.first_failure(report) == (
        "unavailable",
        "unavailable",
        "error",
        "unavailable",
    )


def test_first_failure_is_bounded(tmp_path):
    report = tmp_path / "pytest.xml"
    write_report(
        report,
        f'classname="tests.{"a" * 300}" name="test_{"b" * 200}"><failure>ignored</failure',
    )

    classname, name, phase, reason = summary.first_failure(report)
    assert len(classname) == 240
    assert len(name) == 120
    assert phase == "failure"
    assert reason == "unavailable"


def test_main_emits_one_safe_annotation_for_malformed_report(tmp_path, capsys):
    report = tmp_path / "pytest.xml"
    report.write_text("<not-closed", encoding="utf-8")

    assert summary.main([str(report)]) == 0
    assert capsys.readouterr().out == (
        "::error title=pytest failure::classname=unavailable name=unavailable "
        "phase=session reason=unavailable\n"
    )
