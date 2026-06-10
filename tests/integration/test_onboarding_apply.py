"""Integration test for the setup workflow (form state loading + config persistence).

Runs the bundled setup workflow and verifies:
1. The ``load_state`` step pre-populates form defaults from stores.
2. The ``save`` step persists config when ``generate=true`` is submitted.
3. Without ``generate=true``, only the form is shown (no save).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from beddel.cli import config as config_mod
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import SKIPPED, DefaultDependencies
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.flows import get_bundled_workflow_path
from beddel.primitives import register_builtins


def _make_executor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Build executor with monkeypatched config path and mock tools."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", cfg_path)

    workflow = WorkflowParser.parse(get_bundled_workflow_path("setup").read_text())
    registry = PrimitiveRegistry()
    register_builtins(registry)

    tool_registry = dict(workflow.metadata["_inline_tools"])

    deps = DefaultDependencies(
        registry=registry,
        tool_registry=tool_registry,
    )
    executor = WorkflowExecutor(registry, deps=deps)
    return workflow, executor, tool_registry


@pytest.mark.asyncio()
async def test_apply_flow_persists_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """generate=true triggers save step which persists to SQLite + config.json."""
    workflow, executor, tool_registry = _make_executor(monkeypatch, tmp_path)

    # Mock load_setup to return empty defaults (simulates fresh install)
    mock_load = AsyncMock(
        return_value={
            "llm_provider": "",
            "default_model": "",
            "project_name": "",
            "dashboard_url": "",
            "agent_engine": "",
        }
    )
    tool_registry["load_setup"] = mock_load

    # Mock save_setup to track what was persisted
    mock_save = AsyncMock(
        return_value={
            "saved": True,
            "sqlite_prefs": {"llm_provider": "gemini", "default_model": "gemini-2.0-flash"},
            "config_json_updated": True,
        }
    )
    tool_registry["save_setup"] = mock_save

    result = await executor.execute(
        workflow,
        inputs={
            "llm_provider": "gemini",
            "default_model": "gemini-2.0-flash",
            "project_name": "demo",
            "dashboard_url": "https://connect.beddel.com.br",
            "agent_engine": "my-gcp-project",
            "generate": True,
        },
    )

    step_results = result["step_results"]

    # load_state ran successfully — tool primitive wraps in {tool, result, ...}
    assert step_results["load_state"]["result"] == {
        "llm_provider": "",
        "default_model": "",
        "project_name": "",
        "dashboard_url": "",
        "agent_engine": "",
    }

    # show_form rendered (not skipped)
    assert step_results["show_form"] is not SKIPPED

    # save step ran (generate=true gate)
    assert step_results["save"]["result"]["saved"] is True

    # show_done rendered
    assert step_results["show_done"] is not SKIPPED

    # Verify save_setup was called with correct args
    mock_save.assert_called_once_with(
        llm_provider="gemini",
        default_model="gemini-2.0-flash",
        project_name="demo",
        dashboard_url="https://connect.beddel.com.br",
        agent_engine="my-gcp-project",
    )


@pytest.mark.asyncio()
async def test_preview_renders_form_without_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no flags, load_state + show_form run — save/done are gated out."""
    workflow, executor, tool_registry = _make_executor(monkeypatch, tmp_path)

    mock_load = AsyncMock(
        return_value={
            "llm_provider": "gemini",
            "default_model": "gemini-2.5-flash",
            "project_name": "beddel",
            "dashboard_url": "",
            "agent_engine": "",
        }
    )
    tool_registry["load_setup"] = mock_load

    result = await executor.execute(workflow, inputs={})

    step_results = result["step_results"]

    # load_state ran and returned saved values
    assert step_results["load_state"]["result"]["llm_provider"] == "gemini"

    # show_form rendered the interactive form surface
    assert step_results["show_form"] is not SKIPPED
    surfaces = result["metadata"].get("_a2ui_surfaces", [])
    assert any(s.get("surfaceUpdate", {}).get("id") == "setup-form" for s in surfaces)

    # save and show_done are skipped (generate != true)
    assert step_results["save"] is SKIPPED
    assert step_results["show_done"] is SKIPPED
