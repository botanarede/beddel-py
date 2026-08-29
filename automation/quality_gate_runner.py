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
from collections import Counter
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

_OUTPUT_LIMIT: Final = 8_192
_TERMINATION_GRACE_SECONDS: Final = 5.0
_DEFAULT_TIMEOUT_SECONDS: Final = 300.0
_SCHEMA_DRIFT_TARGET: Final = Path("vendor/beddel/spec/tests/test_schema_sync.py")
_SECRET_PATTERN: Final = re.compile(
    r"(?im)(authorization\s*:\s*(?:bearer\s+)?|"
    r"(?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s'\"]+"
)
_URL_CREDENTIAL_PATTERN: Final = re.compile(r"(https?://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_MYPY_ERROR_PATTERN: Final = re.compile(
    r"^(?P<path>.+?):\d+(?::\d+)?: error: "
    r"(?P<message>.*?)(?:\s+\[(?P<code>[^\]]+)\])?\s*$"
)
_MYPY_SUMMARY_PATTERN: Final = re.compile(
    r"^\s*Found\s+(?P<count>\d+)\s+errors?\s+in\s+\d+\s+files?\b",
    re.MULTILINE,
)
Diagnostic = tuple[str, str, str]


def _disable_local_bytecode_cache() -> None:
    """Prevent this runner from leaving its own import bytecode in the tree."""
    sys.dont_write_bytecode = True
    cache_dir = Path(__file__).with_name("__pycache__")
    if not cache_dir.is_dir():
        return
    for bytecode in cache_dir.glob("*.pyc"):
        with suppress(OSError):
            bytecode.unlink()
    with suppress(OSError):
        cache_dir.rmdir()


_disable_local_bytecode_cache()


class GateOperation(StrEnum):
    """The complete, closed set of bootstrap gate operations."""

    PYTEST = "pytest"
    SCHEMA_DRIFT = "schema-drift"
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
    diagnostics_fingerprint: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class GateReport:
    """Aggregate result for a complete bootstrap-core run."""

    results: tuple[GateResult, ...]
    exit_code: int
    comparison: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        report: dict[str, object] = {
            "exit_code": self.exit_code,
            "results": [asdict(result) for result in self.results],
        }
        if self.comparison is not None:
            report["comparison"] = self.comparison
        return report


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
    try:
        candidate = (root / relative_path).resolve(strict=True)
    except OSError as exc:
        raise GateConfigurationError(f"fixed target cannot be resolved: {relative_path}") from exc
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
        "MYPY_CACHE_DIR": str(home / ".cache" / "mypy"),
        "RUFF_CACHE_DIR": str(home / ".cache" / "ruff"),
        "PYTHONPYCACHEPREFIX": str(home / ".cache" / "pycache"),
    }


def _redact(text: str) -> str:
    """Bound and redact process output before it becomes an evidence record."""
    bounded = text[:_OUTPUT_LIMIT]
    if len(text) > _OUTPUT_LIMIT:
        bounded += "\n[output truncated]"
    redacted = _SECRET_PATTERN.sub(r"\1[REDACTED]", bounded)
    return _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", redacted)


def _relative_diagnostic_path(root: Path, raw_path: str) -> str:
    """Normalize a mypy path relative to the fixed package root."""
    path = Path(raw_path)
    resolved_root = root.resolve()
    if path.is_absolute():
        resolved_path = path.resolve()
        try:
            return resolved_path.relative_to(resolved_root).as_posix()
        except ValueError:
            return os.path.relpath(resolved_path, resolved_root).replace(os.sep, "/")
    return path.as_posix()


def _mypy_diagnostics(root: Path, output: str) -> tuple[Diagnostic, ...]:
    """Extract normalized mypy errors, dropping only line and column numbers."""
    diagnostics: list[Diagnostic] = []
    for line in output.splitlines():
        match = _MYPY_ERROR_PATTERN.match(line)
        if match is None:
            continue
        diagnostics.append(
            (
                _relative_diagnostic_path(root, match.group("path")),
                (match.group("code") or "").strip(),
                match.group("message").strip(),
            )
        )
    return tuple(sorted(diagnostics))


def _report_fingerprint(report: dict[str, object]) -> tuple[Diagnostic, ...]:
    """Read a report fingerprint while accepting reports emitted before this field."""
    results = report.get("results")
    if not isinstance(results, list):
        return ()
    for result in results:
        if not isinstance(result, dict) or result.get("operation") != GateOperation.MYPY.value:
            continue
        fingerprint = result.get("diagnostics_fingerprint", [])
        if not isinstance(fingerprint, list):
            return ()
        diagnostics: list[Diagnostic] = []
        for entry in fingerprint:
            if isinstance(entry, list) and len(entry) == 3:
                diagnostics.append((str(entry[0]), str(entry[1]), str(entry[2])))
        return tuple(diagnostics)
    return ()


def _invalid_comparison(check: str, side: str) -> dict[str, object]:
    return {"reason": {"check": check, "side": side}}


def _validated_mypy_fingerprint(
    report: dict[str, object], side: str
) -> tuple[Diagnostic, ...] | dict[str, object]:
    results = report.get("results")
    if not isinstance(results, list):
        return _invalid_comparison("mypy_operation_present", side)
    mypy_results = [
        result
        for result in results
        if isinstance(result, dict) and result.get("operation") == GateOperation.MYPY.value
    ]
    if not mypy_results:
        return _invalid_comparison("mypy_operation_present", side)
    if len(mypy_results) != 1:
        return _invalid_comparison("mypy_operation_unique", side)

    mypy_result = mypy_results[0]
    returncode = mypy_result.get("returncode")
    if isinstance(returncode, bool) or returncode not in (0, 1):
        return _invalid_comparison("mypy_returncode", side)
    if mypy_result.get("timed_out") is not False:
        return _invalid_comparison("mypy_timed_out", side)

    fingerprint = mypy_result.get("diagnostics_fingerprint")
    if not isinstance(fingerprint, list) or any(
        not isinstance(entry, list) or len(entry) != 3 for entry in fingerprint
    ):
        return _invalid_comparison("mypy_fingerprint", side)
    diagnostics = tuple((str(entry[0]), str(entry[1]), str(entry[2])) for entry in fingerprint)

    stdout = mypy_result.get("stdout", "")
    stderr = mypy_result.get("stderr", "")
    output = "\n".join(value for value in (stdout, stderr) if isinstance(value, str))
    summary_counts = [
        int(match.group("count")) for match in _MYPY_SUMMARY_PATTERN.finditer(output)
    ]
    if summary_counts and any(count != len(diagnostics) for count in summary_counts):
        return _invalid_comparison("mypy_fingerprint_count_matches_summary", side)
    if returncode == 1 and not summary_counts:
        return _invalid_comparison("mypy_summary_present", side)
    return diagnostics


def _compare_report_data(
    base: dict[str, object], candidate: dict[str, object]
) -> dict[str, object]:
    validated: list[tuple[Diagnostic, ...]] = []
    for side, report in (("base", base), ("candidate", candidate)):
        result = _validated_mypy_fingerprint(report, side)
        if isinstance(result, dict):
            return result
        validated.append(result)

    base_counts = Counter(validated[0])
    candidate_counts = Counter(validated[1])

    def entries(counts: Counter[Diagnostic]) -> list[dict[str, object]]:
        return [
            {"path": path, "code": code, "message": message, "count": count}
            for (path, code, message), count in sorted(counts.items())
            if count > 0
        ]

    return {
        "added": entries(candidate_counts - base_counts),
        "removed": entries(base_counts - candidate_counts),
    }


def compare_reports(base_report: str | Path, candidate_report: str | Path) -> dict[str, object]:
    """Return multiplicity-aware mypy diagnostics added to or removed from candidate."""
    reports: list[dict[str, object]] = []
    for side, path in (("base", base_report), ("candidate", candidate_report)):
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _invalid_comparison("readable_report", side)
        if not isinstance(loaded, dict):
            return _invalid_comparison("report_object", side)
        reports.append(loaded)
    return _compare_report_data(reports[0], reports[1])


class QualityGateRunner:
    """Run the fixed Python bootstrap core profile without fail-fast behavior."""

    def __init__(self, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    def run(self, baseline: str | Path | None = None) -> GateReport:
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
        comparison: dict[str, object] | None = None
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

            if baseline is not None:
                candidate_path = Path(temporary_home) / "candidate-report.json"
                candidate_path.write_text(
                    json.dumps({"results": [asdict(result) for result in results]}),
                    encoding="utf-8",
                )
                comparison = compare_reports(baseline, candidate_path)

        invalid_report = any(result.status == "invalid" for result in results)
        invalid_comparison = comparison is not None and "reason" in comparison
        non_mypy_failure = any(
            result.status not in {"passed", "skipped"}
            and result.operation != GateOperation.MYPY.value
            for result in results
        )
        mypy_without_baseline = baseline is None and any(
            result.status != "passed" and result.operation == GateOperation.MYPY.value
            for result in results
        )
        mypy_regression = comparison is not None and bool(comparison.get("added"))

        if invalid_report or invalid_comparison:
            exit_code = 2
        elif non_mypy_failure or mypy_without_baseline or mypy_regression:
            exit_code = 1
        else:
            exit_code = 0
        return GateReport(results=tuple(results), exit_code=exit_code, comparison=comparison)

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
                    "-p",
                    "no:cacheprovider",
                    *checked_pytest_targets,
                    f"--deselect={excluded_mcp_class}",
                ),
            ),
            (
                GateOperation.SCHEMA_DRIFT,
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    _SCHEMA_DRIFT_TARGET.as_posix(),
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
        command_root = root
        command_environment = environment
        if operation is GateOperation.SCHEMA_DRIFT:
            parent_root = root.parent.parent
            expected_package_root = parent_root / "packages" / "beddel-py"
            schema_test = parent_root / _SCHEMA_DRIFT_TARGET
            if expected_package_root.resolve() != root.resolve() or not schema_test.is_file():
                return GateResult(
                    operation=operation.value,
                    status="skipped",
                    returncode=None,
                    duration_seconds=time.monotonic() - started,
                    timed_out=False,
                    stdout=(
                        "Schema drift gate skipped: parent repository schema test "
                        f"not found at {schema_test}"
                    ),
                    stderr="",
                )
            command_root = parent_root
            command_environment = {**environment, "PYTHONPATH": str(root / "src")}

        try:
            process = subprocess.Popen(
                command,
                cwd=command_root,
                env=command_environment,
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
        stdout_text = (stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
        fingerprint = (
            _mypy_diagnostics(root, stdout_text + stderr_text)
            if operation is GateOperation.MYPY
            else ()
        )
        return GateResult(
            operation=operation.value,
            status=status,
            returncode=returncode,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            stdout=_redact(stdout_text),
            stderr=_redact(stderr_text),
            diagnostics_fingerprint=fingerprint,
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the profile or compare two emitted reports."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["compare"]:
        if len(arguments) != 3:
            print(
                "usage: quality_gate_runner.py compare BASE_REPORT CANDIDATE_REPORT",
                file=sys.stderr,
            )
            return 2
        comparison = compare_reports(arguments[1], arguments[2])
        print(json.dumps(comparison, ensure_ascii=False, sort_keys=True))
        if "reason" in comparison:
            return 2
        return 0 if not comparison["added"] else 1

    baseline: str | None = None
    if arguments:
        if len(arguments) != 2 or arguments[0] != "--baseline":
            print("usage: quality_gate_runner.py [--baseline BASELINE_REPORT]", file=sys.stderr)
            return 2
        baseline = arguments[1]
    report = QualityGateRunner().run(baseline=baseline)
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
