"""Deterministic Stage 0 runner for the Python bootstrap core profile.

This module deliberately does not consume workflow YAML.  The accepted
operations, their targets, working directory, environment, and arguments are
all defined here so a workflow cannot widen the command surface.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

_OUTPUT_LIMIT: Final = 8_192
_TERMINATION_GRACE_SECONDS: Final = 5.0
_DEFAULT_TIMEOUT_SECONDS: Final = 300.0
_SECRET_PATTERN: Final = re.compile(
    r"(?im)(authorization\s*:\s*(?:bearer\s+)?|"
    r"(?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s'\"]+"
)
_URL_CREDENTIAL_PATTERN: Final = re.compile(r"(https?://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)


class GateOperation(StrEnum):
    """The complete, closed set of bootstrap gate operations."""

    PYTEST = "pytest"
    RUFF_CHECK = "ruff-check"
    RUFF_FORMAT_CHECK = "ruff-format-check"
    MYPY = "mypy"


@dataclass(frozen=True)
class GateResult:
    """Sanitized result for one fixed operation."""

    operation: str
    status: str
    returncode: int | None
    duration_seconds: float
    timed_out: bool
    stdout: str
    stderr: str


@dataclass(frozen=True)
class GateReport:
    """Aggregate result for a complete bootstrap-core run."""

    results: tuple[GateResult, ...]
    exit_code: int

    def as_dict(self) -> dict[str, object]:
        return {
            "exit_code": self.exit_code,
            "results": [asdict(result) for result in self.results],
        }


class GateConfigurationError(RuntimeError):
    """Raised when the repository layout cannot satisfy the fixed profile."""


def _package_root() -> Path:
    """Resolve the package root from this checked-in module, not caller input."""
    root = Path(__file__).resolve().parent.parent
    if not (root / "pyproject.toml").is_file():
        raise GateConfigurationError("package root does not contain pyproject.toml")
    return root


def _contained_path(root: Path, relative_path: str) -> str:
    """Return a root-relative path only when resolving it cannot escape *root*."""
    candidate = (root / relative_path).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise GateConfigurationError(f"fixed target escapes package root: {relative_path}")
    return str(candidate.relative_to(root))


def _safe_environment(home: Path) -> dict[str, str]:
    """Build a minimal environment rather than inheriting tokens or credentials."""
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "CI": "1",
        "NO_COLOR": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONUTF8": "1",
    }


def _redact(text: str) -> str:
    """Bound and redact process output before it becomes an evidence record."""
    bounded = text[:_OUTPUT_LIMIT]
    if len(text) > _OUTPUT_LIMIT:
        bounded += "\n[output truncated]"
    redacted = _SECRET_PATTERN.sub(r"\1[REDACTED]", bounded)
    return _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", redacted)


class QualityGateRunner:
    """Run the fixed Python bootstrap core profile without fail-fast behavior."""

    def __init__(self, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    def run(self) -> GateReport:
        """Run every operation unless the operator interrupts the process."""
        try:
            root = _package_root()
            commands = self._commands(root)
        except GateConfigurationError as exc:
            result = GateResult(
                operation="bootstrap",
                status="invalid",
                returncode=None,
                duration_seconds=0.0,
                timed_out=False,
                stdout="",
                stderr=_redact(str(exc)),
            )
            return GateReport(results=(result,), exit_code=2)

        results: list[GateResult] = []
        with tempfile.TemporaryDirectory(prefix="beddel-gate-") as temporary_home:
            environment = _safe_environment(Path(temporary_home))
            for operation, command in commands:
                try:
                    result = self._run_operation(operation, command, root, environment)
                except KeyboardInterrupt:
                    interrupted = GateResult(
                        operation=operation.value,
                        status="interrupted",
                        returncode=None,
                        duration_seconds=0.0,
                        timed_out=False,
                        stdout="",
                        stderr="operator interruption",
                    )
                    results.append(interrupted)
                    return GateReport(results=tuple(results), exit_code=130)
                results.append(result)

        if any(result.status == "invalid" for result in results):
            exit_code = 2
        elif any(result.status != "passed" for result in results):
            exit_code = 1
        else:
            exit_code = 0
        return GateReport(results=tuple(results), exit_code=exit_code)

    @staticmethod
    def _commands(root: Path) -> tuple[tuple[GateOperation, tuple[str, ...]], ...]:
        """Construct immutable command tuples from fixed, reviewed targets only."""
        pytest_targets = (
            "tests/automation",
            "tests/adapters",
            "tests/domain",
            "tests/primitives",
            "tests/serve",
            "tests/utils",
            "tests/test_deprecation_warnings.py",
            "tests/test_setup.py",
            "tests/unit/test_onboarding_workflow.py",
        )
        checked_pytest_targets = tuple(_contained_path(root, target) for target in pytest_targets)
        source = _contained_path(root, "src/beddel")
        tests = _contained_path(root, "tests")
        automation = _contained_path(root, "automation")
        excluded_mcp_class = "tests/primitives/test_tool.py::TestMCPSchemaValidation"

        return (
            (
                GateOperation.PYTEST,
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    *checked_pytest_targets,
                    f"--deselect={excluded_mcp_class}",
                ),
            ),
            (
                GateOperation.RUFF_CHECK,
                (sys.executable, "-m", "ruff", "check", source, tests, automation),
            ),
            (
                GateOperation.RUFF_FORMAT_CHECK,
                (sys.executable, "-m", "ruff", "format", "--check", source, tests, automation),
            ),
            (GateOperation.MYPY, (sys.executable, "-m", "mypy", source, automation)),
        )

    def _run_operation(
        self,
        operation: GateOperation,
        command: tuple[str, ...],
        root: Path,
        environment: dict[str, str],
    ) -> GateResult:
        """Run one internally created command in its own process group."""
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return GateResult(
                operation=operation.value,
                status="invalid",
                returncode=None,
                duration_seconds=time.monotonic() - started,
                timed_out=False,
                stdout="",
                stderr=_redact(str(exc)),
            )

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout, stderr = self._terminate_process_group(process)
        except KeyboardInterrupt:
            self._terminate_process_group(process)
            raise

        returncode = process.returncode
        status = "passed" if returncode == 0 and not timed_out else "failed"
        return GateResult(
            operation=operation.value,
            status=status,
            returncode=returncode,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            stdout=_redact((stdout or b"").decode("utf-8", errors="replace")),
            stderr=_redact((stderr or b"").decode("utf-8", errors="replace")),
        )

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
        """Terminate then kill the isolated process group, returning its output."""
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            return process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            return process.communicate()


def main() -> int:
    """Run the profile and emit only sanitized JSON evidence."""
    report = QualityGateRunner().run()
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
