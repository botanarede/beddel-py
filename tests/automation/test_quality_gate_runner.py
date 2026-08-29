"""Tests for the fixed-operation Python bootstrap gate runner."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_runner_module() -> ModuleType:
    """Load repository automation without relying on cwd or ``PYTHONPATH``."""
    module_path = Path(__file__).resolve().parents[2] / "automation" / "quality_gate_runner.py"
    spec = importlib.util.spec_from_file_location("beddel_quality_gate_runner", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the quality gate runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner_module = _load_runner_module()


def _result(operation: runner_module.GateOperation, status: str) -> runner_module.GateResult:
    return runner_module.GateResult(
        operation=operation.value,
        status=status,
        returncode=0 if status == "passed" else 1,
        duration_seconds=0.0,
        timed_out=False,
        stdout="",
        stderr="",
    )


def test_commands_are_closed_and_use_the_current_interpreter() -> None:
    root = Path(__file__).resolve().parents[2]

    commands = runner_module.QualityGateRunner._commands(root)

    assert [operation.value for operation, _ in commands] == [
        "pytest",
        "schema-drift",
        "ruff-check",
        "ruff-format-check",
        "mypy",
    ]
    assert all(command[:3] == (sys.executable, "-m", command[2]) for _, command in commands)
    pytest_command = commands[0][1]
    assert "tests/api" not in pytest_command
    assert "tests/automation" in pytest_command
    assert "tests/unit/test_onboarding_workflow.py" in pytest_command
    assert "--deselect=tests/primitives/test_tool.py::TestMCPSchemaValidation" in pytest_command
    schema_drift_command = commands[1][1]
    assert "vendor/beddel/spec/tests/test_schema_sync.py" in schema_drift_command
    assert all("shell" not in argument for _, command in commands for argument in command)


def test_containment_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside").mkdir()
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(runner_module.GateConfigurationError, match="escapes package root"):
        runner_module._contained_path(root, "escape")


def test_containment_rejects_missing_target(tmp_path: Path) -> None:
    with pytest.raises(
        runner_module.GateConfigurationError,
        match="cannot be resolved: missing-target",
    ):
        runner_module._contained_path(tmp_path, "missing-target")


def test_runner_structures_missing_fixed_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)

    report = runner_module.QualityGateRunner().run()

    assert len(report.results) == 1
    assert report.results[0].operation == "bootstrap"
    assert report.results[0].status == "invalid"
    assert report.results[0].returncode is None
    assert report.exit_code == 2
    assert "cannot be resolved" in report.results[0].stderr
    assert "tests/automation" in report.results[0].stderr


def test_safe_environment_drops_inherited_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "must-not-leak")

    environment = runner_module._safe_environment(tmp_path)

    assert "SECRET_TOKEN" not in environment
    assert environment["HOME"] == str(tmp_path)
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["MYPY_CACHE_DIR"] == str(tmp_path / ".cache" / "mypy")
    assert environment["RUFF_CACHE_DIR"] == str(tmp_path / ".cache" / "ruff")
    assert environment["PYTHONPYCACHEPREFIX"] == str(tmp_path / ".cache" / "pycache")


def test_pytest_disables_cache_provider() -> None:
    root = Path(__file__).resolve().parents[2]
    pytest_command = dict(runner_module.QualityGateRunner._commands(root))[
        runner_module.GateOperation.PYTEST
    ]

    assert "-p" in pytest_command
    assert pytest_command[pytest_command.index("-p") + 1] == "no:cacheprovider"


def test_schema_drift_gate_skips_in_isolated_clone(tmp_path: Path) -> None:
    root = tmp_path / "beddel-py"
    root.mkdir()
    runner = runner_module.QualityGateRunner()

    result = runner._run_operation(
        runner_module.GateOperation.SCHEMA_DRIFT,
        (sys.executable, "-m", "pytest"),
        root,
        runner_module._safe_environment(tmp_path),
    )

    assert result.status == "skipped"
    assert result.returncode is None
    assert "parent repository schema test not found" in result.stdout


def test_schema_drift_skip_is_non_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)

    def fake_run(
        self: runner_module.QualityGateRunner,
        operation: runner_module.GateOperation,
        command: tuple[str, ...],
        command_root: Path,
        environment: dict[str, str],
    ) -> runner_module.GateResult:
        del self, command, command_root, environment
        if operation is runner_module.GateOperation.SCHEMA_DRIFT:
            return runner_module.GateResult(
                operation=operation.value,
                status="skipped",
                returncode=None,
                duration_seconds=0.0,
                timed_out=False,
                stdout="parent repository schema test not found",
                stderr="",
            )
        return _result(operation, "passed")

    monkeypatch.setattr(runner_module.QualityGateRunner, "_run_operation", fake_run)

    report = runner_module.QualityGateRunner().run()

    assert report.exit_code == 0
    assert report.results[1].status == "skipped"


def test_mypy_fingerprint_drops_position_but_keeps_identity(tmp_path: Path) -> None:
    root = tmp_path / "package"
    root.mkdir()
    first = runner_module._mypy_diagnostics(
        root,
        "src/a.py:10:2: error: bad type  [arg-type]\n"
        "src/b.py:4: error: missing name  [name-defined]\n",
    )
    same_diagnostics = runner_module._mypy_diagnostics(
        root,
        "src/a.py:99:20: error: bad type  [arg-type]\n"
        "src/b.py:40:7: error: missing name  [name-defined]\n",
    )
    different_diagnostics = runner_module._mypy_diagnostics(
        root,
        "src/a.py:99:20: error: changed type  [assignment]\n"
        "src/c.py:40:7: error: missing name  [name-defined]\n",
    )

    assert first == same_diagnostics
    assert first != different_diagnostics


def _mypy_report_data(
    diagnostics: list[runner_module.Diagnostic],
    *,
    timed_out: bool = False,
    stdout: str | None = None,
) -> dict[str, object]:
    resolved_returncode = 1 if diagnostics else 0
    summary = (
        f"Found {len(diagnostics)} error{'s' if len(diagnostics) != 1 else ''} in 1 file\n"
        if diagnostics
        else "Success: no issues found in 1 source file\n"
    )
    return {
        "exit_code": resolved_returncode,
        "results": [
            {
                "operation": "mypy",
                "status": "failed" if resolved_returncode else "passed",
                "returncode": resolved_returncode,
                "duration_seconds": 0.0,
                "timed_out": timed_out,
                "stdout": summary if stdout is None else stdout,
                "stderr": "",
                "diagnostics_fingerprint": [list(diagnostic) for diagnostic in diagnostics],
            }
        ],
    }


def _write_mypy_report(path: Path, diagnostics: list[runner_module.Diagnostic]) -> None:
    path.write_text(json.dumps(_mypy_report_data(diagnostics)), encoding="utf-8")


def test_compare_reports_detects_changes_and_multiplicity(tmp_path: Path) -> None:
    unchanged = ("src/a.py", "arg-type", "bad type")
    removed = ("src/b.py", "name-defined", "missing name")
    added = ("src/c.py", "assignment", "changed type")
    base_path = tmp_path / "base.json"
    candidate_path = tmp_path / "candidate.json"
    _write_mypy_report(base_path, [unchanged, unchanged, removed])
    _write_mypy_report(candidate_path, [unchanged, added, added])

    comparison = runner_module.compare_reports(base_path, candidate_path)

    assert comparison == {
        "added": [
            {
                "path": "src/c.py",
                "code": "assignment",
                "message": "changed type",
                "count": 2,
            }
        ],
        "removed": [
            {
                "path": "src/a.py",
                "code": "arg-type",
                "message": "bad type",
                "count": 1,
            },
            {
                "path": "src/b.py",
                "code": "name-defined",
                "message": "missing name",
                "count": 1,
            },
        ],
    }


def test_redaction_and_output_cap() -> None:
    text = "token=abc123 Authorization: Bearer xyz https://alice:pw@example.test " + ("x" * 9_000)

    redacted = runner_module._redact(text)

    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert "alice:pw" not in redacted
    assert "[REDACTED]" in redacted
    assert "[output truncated]" in redacted


def _mypy_result(report: dict[str, object]) -> dict[str, object]:
    results = report["results"]
    assert isinstance(results, list)
    result = results[0]
    assert isinstance(result, dict)
    return result


@pytest.mark.parametrize(
    ("mutation", "expected_check"),
    [
        ("missing_operation", "mypy_operation_present"),
        ("returncode_two", "mypy_returncode"),
        ("returncode_none", "mypy_returncode"),
        ("timed_out", "mypy_timed_out"),
        ("fingerprint_count", "mypy_fingerprint_count_matches_summary"),
        ("summary_absent", "mypy_summary_present"),
    ],
)
@pytest.mark.parametrize("side", ["base", "candidate"])
def test_compare_reports_rejects_each_untrustworthy_mypy_report(
    tmp_path: Path, side: str, mutation: str, expected_check: str
) -> None:
    diagnostic = ("src/a.py", "arg-type", "bad type")
    reports = [_mypy_report_data([diagnostic]), _mypy_report_data([diagnostic])]
    selected = reports[0 if side == "base" else 1]
    if mutation == "missing_operation":
        _mypy_result(selected)["operation"] = "pytest"
    elif mutation == "returncode_two":
        _mypy_result(selected)["returncode"] = 2
    elif mutation == "returncode_none":
        _mypy_result(selected)["returncode"] = None
    elif mutation == "timed_out":
        _mypy_result(selected)["timed_out"] = True
    elif mutation == "fingerprint_count":
        _mypy_result(selected)["stdout"] = "Found 2 errors in 1 file\n"
    elif mutation == "summary_absent":
        _mypy_result(selected)["stdout"] = ""

    base_path = tmp_path / "base.json"
    candidate_path = tmp_path / "candidate.json"
    base_path.write_text(json.dumps(reports[0]), encoding="utf-8")
    candidate_path.write_text(json.dumps(reports[1]), encoding="utf-8")

    comparison = runner_module.compare_reports(base_path, candidate_path)

    assert comparison == {"reason": {"check": expected_check, "side": side}}


def test_runner_aggregates_failures_without_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    calls: list[runner_module.GateOperation] = []

    monkeypatch.setattr(runner_module, "_package_root", lambda: root)

    def fake_run(
        self: runner_module.QualityGateRunner,
        operation: runner_module.GateOperation,
        command: tuple[str, ...],
        command_root: Path,
        environment: dict[str, str],
    ) -> runner_module.GateResult:
        del self, command, command_root, environment
        calls.append(operation)
        status = "failed" if operation is runner_module.GateOperation.PYTEST else "passed"
        return _result(operation, status)

    monkeypatch.setattr(runner_module.QualityGateRunner, "_run_operation", fake_run)

    report = runner_module.QualityGateRunner().run()

    assert report.exit_code == 1
    assert calls == list(runner_module.GateOperation)
    assert report.results[0].status == "failed"
    assert all(result.status == "passed" for result in report.results[1:])


def test_runner_mypy_failure_is_blocking_without_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)

    def fake_run(
        self: runner_module.QualityGateRunner,
        operation: runner_module.GateOperation,
        command: tuple[str, ...],
        command_root: Path,
        environment: dict[str, str],
    ) -> runner_module.GateResult:
        del self, command, command_root, environment
        return _result(
            operation,
            "failed" if operation is runner_module.GateOperation.MYPY else "passed",
        )

    monkeypatch.setattr(runner_module.QualityGateRunner, "_run_operation", fake_run)

    report = runner_module.QualityGateRunner().run()

    assert report.results[-1].operation == "mypy"
    assert report.results[-1].status == "failed"
    assert report.exit_code == 1


def test_runner_mypy_failure_with_valid_baseline_and_no_additions_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)
    diagnostic = ("src/a.py", "arg-type", "bad type")

    def fake_run(
        self: runner_module.QualityGateRunner,
        operation: runner_module.GateOperation,
        command: tuple[str, ...],
        command_root: Path,
        environment: dict[str, str],
    ) -> runner_module.GateResult:
        del self, command, command_root, environment
        if operation is runner_module.GateOperation.MYPY:
            return runner_module.GateResult(
                operation=operation.value,
                status="failed",
                returncode=1,
                duration_seconds=0.0,
                timed_out=False,
                stdout="Found 1 error in 1 file\n",
                stderr="",
                diagnostics_fingerprint=(diagnostic,),
            )
        return _result(operation, "passed")

    monkeypatch.setattr(runner_module.QualityGateRunner, "_run_operation", fake_run)
    baseline = tmp_path / "baseline.json"
    _write_mypy_report(baseline, [diagnostic])

    report = runner_module.QualityGateRunner().run(baseline=baseline)

    assert report.exit_code == 0
    assert report.comparison == {"added": [], "removed": []}


def test_runner_mypy_additions_with_valid_baseline_are_blocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)
    baseline_diagnostic = ("src/a.py", "arg-type", "bad type")
    added_diagnostic = ("src/b.py", "name-defined", "missing name")

    def fake_run(
        self: runner_module.QualityGateRunner,
        operation: runner_module.GateOperation,
        command: tuple[str, ...],
        command_root: Path,
        environment: dict[str, str],
    ) -> runner_module.GateResult:
        del self, command, command_root, environment
        if operation is runner_module.GateOperation.MYPY:
            return runner_module.GateResult(
                operation=operation.value,
                status="failed",
                returncode=1,
                duration_seconds=0.0,
                timed_out=False,
                stdout="Found 2 errors in 1 file\n",
                stderr="",
                diagnostics_fingerprint=(baseline_diagnostic, added_diagnostic),
            )
        return _result(operation, "passed")

    monkeypatch.setattr(runner_module.QualityGateRunner, "_run_operation", fake_run)
    baseline = tmp_path / "baseline.json"
    _write_mypy_report(baseline, [baseline_diagnostic])

    report = runner_module.QualityGateRunner().run(baseline=baseline)

    assert report.exit_code == 1
    assert report.comparison is not None
    assert report.comparison["added"]


def test_runner_invalid_baseline_is_blocking_with_exit_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)
    monkeypatch.setattr(
        runner_module.QualityGateRunner,
        "_run_operation",
        lambda self, operation, command, command_root, environment: _result(operation, "passed"),
    )
    baseline = tmp_path / "invalid.json"
    baseline.write_text("not json", encoding="utf-8")

    report = runner_module.QualityGateRunner().run(baseline=baseline)

    assert report.exit_code == 2
    assert report.comparison == {"reason": {"check": "readable_report", "side": "base"}}


def test_runner_process_leaves_no_cache_artifacts() -> None:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    # The gate invokes pytest with PYTHONSAFEPATH=1, so cwd is not an import path.
    environment["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        [sys.executable, "-m", "automation.quality_gate_runner", "--invalid"],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    cache_names = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    cache_paths = (
        path for path in root.rglob("*") if ".venv" not in path.parts and path.name in cache_names
    )
    assert not any(cache_paths)


def test_runner_returns_two_when_fixed_layout_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_module,
        "_package_root",
        lambda: (_ for _ in ()).throw(runner_module.GateConfigurationError("bad root")),
    )

    report = runner_module.QualityGateRunner().run()

    assert report.exit_code == 2
    assert report.results[0].status == "invalid"


def test_runner_returns_130_on_operator_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner_module, "_package_root", lambda: root)

    def interrupted(*args: object, **kwargs: object) -> runner_module.GateResult:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(runner_module.QualityGateRunner, "_run_operation", interrupted)

    report = runner_module.QualityGateRunner().run()

    assert report.exit_code == 130
    assert report.results[0].status == "interrupted"


def test_process_runner_uses_a_real_process_group_and_sanitized_environment(
    tmp_path: Path,
) -> None:
    """A controlled child process proves the private subprocess boundary works."""
    root = Path(__file__).resolve().parents[2]
    runner = runner_module.QualityGateRunner(timeout_seconds=5)
    environment = runner_module._safe_environment(tmp_path)
    command = (sys.executable, "-c", "import os; print(os.environ.get('SECRET_TOKEN', 'clean'))")

    result = runner._run_operation(runner_module.GateOperation.PYTEST, command, root, environment)

    assert result.status == "passed"
    assert result.stdout.strip() == "clean"
    assert result.timed_out is False


def test_timeout_terminates_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    runner = runner_module.QualityGateRunner(timeout_seconds=0.01)

    class TimedOutProcess:
        pid = os.getpid()
        returncode = -signal.SIGTERM

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            if timeout == runner._timeout_seconds:
                raise subprocess.TimeoutExpired("fixed", timeout)
            return b"", b""

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: TimedOutProcess())
    monkeypatch.setattr(os, "killpg", lambda *args, **kwargs: None)

    result = runner._run_operation(
        runner_module.GateOperation.PYTEST,
        (sys.executable, "-m", "pytest"),
        root,
        runner_module._safe_environment(root),
    )

    assert result.timed_out is True
    assert result.status == "failed"
