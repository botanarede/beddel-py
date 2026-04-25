"""Tests for workflow auto-discovery logic in ``_build_runtime_app``.

Story BC6.4 — Workflow Auto-Discovery.

Exercises the discovery block inside ``_build_runtime_app`` by invoking
``beddel serve`` via ``CliRunner`` with no ``--workflow`` flags (which
triggers auto-discovery).  Heavy dependencies (FastAPI, uvicorn, etc.)
are stubbed so only the file-scanning logic runs against real files in
a temporary directory.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Valid / invalid YAML content helpers
# ---------------------------------------------------------------------------

_VALID_WORKFLOW_YAML = """\
name: Test Workflow
steps:
  - id: s1
    primitive: llm
    config:
      model: test/model
      prompt: hello
"""

_VALID_WORKFLOW_YAML_YML = """\
name: Another Workflow
steps:
  - id: s1
    primitive: llm
    config:
      model: test/model
      prompt: world
"""

_INVALID_YAML_NO_STEPS = """\
name: Not A Workflow
description: Missing steps key
"""

_INVALID_YAML_NO_NAME = """\
steps:
  - id: s1
    primitive: llm
"""

_PLAIN_CONFIG_YAML = """\
database:
  host: localhost
  port: 5432
"""


# ---------------------------------------------------------------------------
# Fixture: stub heavy dependencies so _build_runtime_app can execute
# ---------------------------------------------------------------------------


@pytest.fixture()
def _stub_heavy_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch heavy imports so ``_build_runtime_app`` runs the discovery block.

    Stubs: FastAPI, CORSMiddleware, uvicorn, beddel_serve_fastapi,
    WorkflowParser.parse, discover_kits, _build_adapter_registries,
    _build_tool_registry, _parse_tool_flags, _ensure_kit_paths.
    """
    # -- FastAPI stubs -------------------------------------------------------
    fake_fastapi = types.ModuleType("fastapi")

    class _FakeApp:
        def __init__(self, **kw: Any) -> None:
            self.routes: list[Any] = []

        def add_middleware(self, *a: Any, **kw: Any) -> None:
            pass

        def include_router(self, *a: Any, **kw: Any) -> None:
            pass

        def get(self, path: str) -> Any:
            def _dec(fn: Any) -> Any:
                return fn

            return _dec

    fake_fastapi.FastAPI = _FakeApp  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastapi", fake_fastapi)

    fake_cors_pkg = types.ModuleType("fastapi.middleware")
    monkeypatch.setitem(sys.modules, "fastapi.middleware", fake_cors_pkg)

    fake_cors = types.ModuleType("fastapi.middleware.cors")
    fake_cors.CORSMiddleware = type("CORSMiddleware", (), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastapi.middleware.cors", fake_cors)

    # -- uvicorn stub --------------------------------------------------------
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **kw: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    # -- beddel_serve_fastapi stub -------------------------------------------
    fake_bsf = types.ModuleType("beddel_serve_fastapi")
    monkeypatch.setitem(sys.modules, "beddel_serve_fastapi", fake_bsf)

    fake_bsf_h = types.ModuleType("beddel_serve_fastapi.handler")
    fake_bsf_h.create_beddel_handler = lambda *a, **kw: MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "beddel_serve_fastapi.handler", fake_bsf_h)

    # -- WorkflowParser.parse → returns mock Workflow with .id ---------------
    mock_wf = MagicMock()
    mock_wf.id = "test-wf"
    monkeypatch.setattr(
        "beddel.domain.parser.WorkflowParser.parse",
        staticmethod(lambda _yaml: mock_wf),
    )

    # -- discover_kits → empty result ---------------------------------------
    mock_kit_result = MagicMock()
    mock_kit_result.kit_paths = []
    mock_kit_result.adapters = {}
    monkeypatch.setattr(
        "beddel.tools.kits.discover_kits",
        lambda *_a, **_kw: mock_kit_result,
    )

    # -- _build_adapter_registries → (mock, mock) ---------------------------
    monkeypatch.setattr(
        "beddel.cli.commands._build_adapter_registries",
        lambda *_a, **_kw: (MagicMock(), MagicMock()),
    )

    # -- _build_tool_registry → mock ----------------------------------------
    monkeypatch.setattr(
        "beddel.cli.commands._build_tool_registry",
        lambda *_a, **_kw: MagicMock(),
    )

    # -- _parse_tool_flags → empty dict -------------------------------------
    monkeypatch.setattr(
        "beddel.cli.commands._parse_tool_flags",
        lambda *_a, **_kw: {},
    )

    # -- _ensure_kit_paths → noop -------------------------------------------
    monkeypatch.setattr(
        "beddel.cli.commands._ensure_kit_paths",
        lambda: None,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _invoke_serve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    extra_args: list[str] | None = None,
) -> Any:
    """``chdir`` into *tmp_path* and invoke ``beddel serve`` via CliRunner."""
    monkeypatch.chdir(tmp_path)

    # Reload commands module so the lazy imports inside _build_runtime_app
    # pick up our patched sys.modules.
    from beddel.cli.commands import cli

    runner = CliRunner()
    args = ["serve", *(extra_args or [])]
    return runner.invoke(cli, args, catch_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkflowDiscoveryCWD:
    """AC #1 — valid workflow YAML in CWD is discovered."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_discovers_yaml_in_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        (tmp_path / "my-flow.yaml").write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: my-flow.yaml" in result.output

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_discovers_yml_extension(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "flow.yml").write_text(_VALID_WORKFLOW_YAML_YML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: flow.yml" in result.output


class TestWorkflowDiscoverySubdir:
    """AC #2 — valid workflow YAML in ``workflows/`` subdirectory is discovered."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_discovers_yaml_in_workflows_subdir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "sub-flow.yaml").write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: sub-flow.yaml" in result.output

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_discovers_yml_in_workflows_subdir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "sub-flow.yml").write_text(_VALID_WORKFLOW_YAML_YML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: sub-flow.yml" in result.output


class TestWorkflowDiscoverySkipsNonWorkflow:
    """AC #3 — non-workflow YAML (missing ``name:`` or ``steps:``) is skipped."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_skips_yaml_without_steps(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "no-steps.yaml").write_text(_INVALID_YAML_NO_STEPS)
        # Need at least one valid workflow or we get the warning path
        # — but we specifically want to test that the invalid one is skipped.
        # So we also add a valid one.
        (tmp_path / "valid.yaml").write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: no-steps.yaml" not in result.output
        assert "Discovered: valid.yaml" in result.output

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_skips_yaml_without_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "no-name.yaml").write_text(_INVALID_YAML_NO_NAME)
        (tmp_path / "valid.yaml").write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: no-name.yaml" not in result.output
        assert "Discovered: valid.yaml" in result.output

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_skips_plain_config_yaml(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "config.yaml").write_text(_PLAIN_CONFIG_YAML)
        (tmp_path / "valid.yaml").write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: config.yaml" not in result.output
        assert "Discovered: valid.yaml" in result.output


class TestWorkflowDiscoveryOverride:
    """AC #5 — ``--workflow`` flag overrides auto-discovery."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_explicit_workflow_skips_discovery(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Place a discoverable file in CWD
        (tmp_path / "auto.yaml").write_text(_VALID_WORKFLOW_YAML)
        # Also create the explicit workflow file
        explicit = tmp_path / "explicit.yaml"
        explicit.write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path, extra_args=["-w", str(explicit)])

        assert result.exit_code == 0, result.output + result.stderr
        # Discovery messages should NOT appear — explicit path was used
        assert "Discovered:" not in result.output
        # The explicit workflow should be mounted
        assert "Mounted:" in result.output


class TestWorkflowDiscoveryWarning:
    """AC #6 — zero workflows found emits warning to stderr."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_no_workflows_emits_warning(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Empty directory — no YAML files at all
        result = _invoke_serve(monkeypatch, tmp_path)

        # The warning goes to stderr
        assert "Warning: No workflows found" in result.stderr

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_only_invalid_yaml_emits_warning(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Only non-workflow YAML present
        (tmp_path / "config.yaml").write_text(_PLAIN_CONFIG_YAML)
        (tmp_path / "no-steps.yaml").write_text(_INVALID_YAML_NO_STEPS)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert "Warning: No workflows found" in result.stderr


class TestWorkflowDiscoveryDedup:
    """AC #7 — duplicate file in CWD and ``workflows/`` is deduplicated."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_symlinked_duplicate_loaded_once(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A symlink in ``workflows/`` pointing to a CWD file is loaded once."""
        cwd_file = tmp_path / "shared.yaml"
        cwd_file.write_text(_VALID_WORKFLOW_YAML)

        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        symlink = wf_dir / "shared.yaml"
        symlink.symlink_to(cwd_file)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        # "Discovered:" should appear exactly once for this resolved path
        discovered_lines = [
            ln for ln in result.output.splitlines() if "Discovered: shared.yaml" in ln
        ]
        assert len(discovered_lines) == 1, (
            f"Expected 1 discovery of shared.yaml, got {len(discovered_lines)}:\n" + result.output
        )


class TestWorkflowDiscoveryLogging:
    """AC #2 (logging) — discovery logs each found file name."""

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_logs_each_discovered_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "alpha.yaml").write_text(_VALID_WORKFLOW_YAML)
        (tmp_path / "beta.yml").write_text(_VALID_WORKFLOW_YAML_YML)

        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "gamma.yaml").write_text(_VALID_WORKFLOW_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: alpha.yaml" in result.output
        assert "Discovered: beta.yml" in result.output
        assert "Discovered: gamma.yaml" in result.output

    @pytest.mark.usefixtures("_stub_heavy_deps")
    def test_does_not_log_skipped_files(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "valid.yaml").write_text(_VALID_WORKFLOW_YAML)
        (tmp_path / "invalid.yaml").write_text(_PLAIN_CONFIG_YAML)

        result = _invoke_serve(monkeypatch, tmp_path)

        assert result.exit_code == 0, result.output + result.stderr
        assert "Discovered: valid.yaml" in result.output
        assert "Discovered: invalid.yaml" not in result.output
