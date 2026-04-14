"""Tests for CLI kit import guards (Story 8.2).

Verify that each CLI command prints a helpful error message and exits
with code 1 when its required kit package is not installed.
"""

from __future__ import annotations

import subprocess
import sys


def _run_guarded(
    blocked_module: str,
    cli_args: list[str],
) -> tuple[int, str]:
    """Run a CLI command in a subprocess with *blocked_module* unavailable.

    Uses a ``sys.meta_path`` blocker injected before the CLI import so
    the guard fires reliably — even when the kit IS installed in the
    test environment.

    Returns ``(exit_code, combined_output)`` as reported by the
    subprocess script.
    """
    script = f"""\
import sys
import importlib.abc
import importlib.machinery

class _Blocker(importlib.abc.MetaPathFinder):
    \"\"\"Meta-path finder that blocks a top-level package.\"\"\"
    def __init__(self, pkg: str) -> None:
        self.pkg = pkg
    def find_spec(self, fullname, path, target=None):
        if fullname == self.pkg or fullname.startswith(self.pkg + "."):
            # Return a spec that will fail to load
            raise ImportError(f"Blocked by test: {{fullname}}")
        return None

# Remove any cached entries for the blocked package
blocked = "{blocked_module}"
for key in list(sys.modules):
    if key == blocked or key.startswith(blocked + "."):
        del sys.modules[key]

sys.meta_path.insert(0, _Blocker(blocked))

from click.testing import CliRunner
from beddel.cli.commands import cli

runner = CliRunner()
result = runner.invoke(cli, {cli_args!r}, catch_exceptions=True)
combined = result.output or ""
print(f"EXIT:{{result.exit_code}}")
print(f"OUTPUT:{{combined}}")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = proc.stdout
    # If the subprocess itself crashed, include stderr for diagnostics
    if proc.returncode != 0 and "EXIT:" not in stdout:
        stdout += proc.stderr
    return proc.returncode, stdout


# ── beddel status ─────────────────────────────────────────────────


class TestStatusImportGuard:
    """``beddel status`` must exit 1 with helpful message when auth-github-kit is missing."""

    def test_missing_auth_github_kit(self) -> None:
        _rc, out = _run_guarded("beddel_auth_github", ["status"])
        assert "EXIT:1" in out, f"Expected exit 1, got: {out}"
        assert "Missing dependency" in out, f"Missing 'Missing dependency' in: {out}"
        assert "pip install beddel[default]" in out, f"Missing install hint in: {out}"


# ── beddel connect ────────────────────────────────────────────────


class TestConnectImportGuard:
    """``beddel connect`` must exit 1 with helpful message when auth-github-kit is missing."""

    def test_missing_auth_github_kit(self) -> None:
        _rc, out = _run_guarded("beddel_auth_github", ["connect"])
        assert "EXIT:1" in out, f"Expected exit 1, got: {out}"
        assert "Missing dependency" in out, f"Missing 'Missing dependency' in: {out}"
        assert "pip install beddel[default]" in out, f"Missing install hint in: {out}"


# ── beddel serve --mcp ────────────────────────────────────────────


class TestServeMcpImportGuard:
    """``beddel serve --mcp`` must exit 1 when serve-mcp-kit is missing."""

    def test_missing_mcp_kit(self) -> None:
        _rc, out = _run_guarded("beddel_serve_mcp", ["serve", "--mcp"])
        assert "EXIT:1" in out, f"Expected exit 1, got: {out}"
        assert "Missing dependency" in out, f"Missing 'Missing dependency' in: {out}"
        assert "pip install beddel[mcp]" in out, f"Missing install hint in: {out}"


# ── beddel serve (FastAPI mode) ───────────────────────────────────


class TestServeFastapiImportGuard:
    """``beddel serve`` (FastAPI) must exit 1 when serve-fastapi-kit is missing.

    The ``serve`` command has TWO guards in FastAPI mode:
    1. ``uvicorn`` / ``fastapi`` — "Missing dependencies"
    2. ``beddel_serve_fastapi`` — "Missing dependency"

    If uvicorn IS available in the test env, blocking
    ``beddel_serve_fastapi`` triggers guard #2.  If uvicorn is NOT
    available, guard #1 fires first.  Either way the command must
    exit 1 with a helpful message.
    """

    def test_missing_fastapi_kit(self) -> None:
        _rc, out = _run_guarded("beddel_serve_fastapi", ["serve"])
        assert "EXIT:1" in out, f"Expected exit 1, got: {out}"
        # Accept either guard's wording
        has_guard = "Missing dependency" in out or "Missing dependencies" in out
        assert has_guard, f"Missing dependency message in: {out}"
        assert "beddel[default]" in out, f"Missing install hint in: {out}"
