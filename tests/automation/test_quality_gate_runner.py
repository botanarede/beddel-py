"""Tests for the fixed-operation Python bootstrap gate runner."""

from __future__ import annotations

import importlib.util
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


def test_runner_structures_missing_fixed_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    assert environment["PYTHONPYCACHEPREFIX"] == str(tmp_path / ".cache" / "pycache")


def test_pytest_disables_cache_provider() -> None:
    root = Path(__file__).resolve().parents[2]
    pytest_command = dict(runner_module.QualityGateRunner._commands(root))[
        runner_module.GateOperation.PYTEST
    ]

    assert "-p" in pytest_command
    assert pytest_command[pytest_command.index("-p") + 1] == "no:cacheprovider"


def test_redaction_and_output_cap() -> None:
    text = "token=abc123 Authorization: Bearer xyz https://alice:pw@example.test " + ("x" * 9_000)

    redacted = runner_module._redact(text)

    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert "alice:pw" not in redacted
    assert "[REDACTED]" in redacted
    assert "[output truncated]" in redacted


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
