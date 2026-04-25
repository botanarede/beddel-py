"""Unit tests verifying ``beddel serve`` has no ``--dashboard`` flag (Story BC6.3, Task 4).

Verifies:
- ``serve --help`` does NOT advertise a ``--dashboard`` option (AC #6).
- ``serve`` never imports ``beddel_ag_ui`` — AG-UI is connect-only (AC #6).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class TestNoDashboardFlagInServe:
    """BC6.3 — ``serve --help`` does NOT include a ``--dashboard`` option.

    The ``--dashboard`` flag was removed in BC6.3.  AG-UI endpoints are
    now mounted exclusively by the ``connect`` command.
    """

    def test_help_does_not_contain_dashboard_option(self) -> None:
        from click.testing import CliRunner

        from beddel.cli.commands import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])

        assert result.exit_code == 0, result.output
        assert "--dashboard" not in result.output


class TestNoDashboardSkipsAguiImport:
    """BC6.3 — ``serve`` never imports ``beddel_ag_ui`` (dashboard flag removed).

    Since ``--dashboard`` was removed in BC6.3, ``serve`` must never
    trigger an import of ``beddel_ag_ui``.  AG-UI endpoints are mounted
    exclusively by the ``connect`` command.

    Runs in a subprocess so that module-level side effects from the
    test environment do not interfere.  A ``sys.meta_path`` blocker
    records whether ``beddel_ag_ui`` was ever requested during the
    invocation.
    """

    def test_no_agui_import_without_flag(self, tmp_path: Path) -> None:
        """Invoke ``serve`` and verify ``beddel_ag_ui`` is never imported."""
        wf_file = tmp_path / "hello.yaml"
        wf_file.write_text(
            "id: hello-world\n"
            "name: Hello World\n"
            "steps:\n"
            "  - id: s1\n"
            "    primitive: llm\n"
            "    config:\n"
            "      model: test/model\n"
            "      prompt: hello\n"
        )

        script = _build_subprocess_script(str(wf_file))

        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )

        stdout = proc.stdout
        if proc.returncode != 0 and "AGUI_IMPORTED:" not in stdout:
            stdout += proc.stderr

        assert "AGUI_IMPORTED:no" in stdout, (
            f"Expected beddel_ag_ui to NOT be imported, got:\n{stdout}\nstderr:\n{proc.stderr}"
        )


def _build_subprocess_script(wf_path: str) -> str:
    """Return a Python script that invokes ``serve`` (no AG-UI — dashboard flag removed in BC6.3).

    The script installs a ``sys.meta_path`` spy that detects any attempt
    to import ``beddel_ag_ui``.  The ``serve`` command will fail early
    (no uvicorn in subprocess) but the import spy fires before that,
    which is what we care about.
    """
    return f'''\
import sys
import types
import importlib.abc

# ── Spy: detect any attempt to import beddel_ag_ui ──────────────
_agui_requested = False

class _ImportSpy(importlib.abc.MetaPathFinder):
    """Records whether beddel_ag_ui was ever requested."""
    def find_spec(self, fullname, path, target=None):
        global _agui_requested
        if fullname == "beddel_ag_ui" or fullname.startswith("beddel_ag_ui."):
            _agui_requested = True
        return None  # let normal import machinery continue

sys.meta_path.insert(0, _ImportSpy())

# ── Fake heavy deps so serve() reaches the dashboard guard ──────
# Provide minimal stubs for uvicorn, fastapi, and beddel_serve_fastapi
# so the command doesn't exit at the first import guard.

_uvi = types.ModuleType("uvicorn")
_uvi.run = lambda *a, **kw: None  # type: ignore[attr-defined]
sys.modules["uvicorn"] = _uvi

_fa = types.ModuleType("fastapi")
class _FakeApp:
    def __init__(self, **kw): self.routes = []
    def add_middleware(self, *a, **kw): pass
    def include_router(self, *a, **kw): pass
    def get(self, path):
        def _dec(fn): return fn
        return _dec
_fa.FastAPI = _FakeApp  # type: ignore[attr-defined]
sys.modules["fastapi"] = _fa

_cors = types.ModuleType("fastapi.middleware")
sys.modules["fastapi.middleware"] = _cors
_cors_mod = types.ModuleType("fastapi.middleware.cors")
_cors_mod.CORSMiddleware = type("CORSMiddleware", (), {{}})  # type: ignore[attr-defined]
sys.modules["fastapi.middleware.cors"] = _cors_mod

_bsf = types.ModuleType("beddel_serve_fastapi")
sys.modules["beddel_serve_fastapi"] = _bsf
_bsf_h = types.ModuleType("beddel_serve_fastapi.handler")

class _FakeRouter:
    pass

def _fake_handler(workflow, **kw):
    return _FakeRouter()

_bsf_h.create_beddel_handler = _fake_handler  # type: ignore[attr-defined]
sys.modules["beddel_serve_fastapi.handler"] = _bsf_h

# ── Invoke the CLI ──────────────────────────────────────────────
from click.testing import CliRunner
from beddel.cli.commands import cli

runner = CliRunner()
# Invoke serve (no AG-UI — dashboard flag removed in BC6.3)
result = runner.invoke(
    cli,
    ["serve", "-w", "{wf_path}"],
    catch_exceptions=True,
)

# Report whether beddel_ag_ui was ever requested
print(f"AGUI_IMPORTED:{{"yes" if _agui_requested else "no"}}")
print(f"EXIT:{{result.exit_code}}")
'''
