"""Integration test for the onboarding Apply flow (config persistence).

Runs the bundled onboarding workflow with ``apply=true`` and verifies the
gated ``save_config`` step persists the generated config while the
LLM/generate steps are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beddel.cli import config as config_mod
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import SKIPPED, DefaultDependencies
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.flows import get_onboarding_workflow_path
from beddel.primitives import register_builtins


async def test_apply_flow_persists_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """apply=true skips generate/show_config and persists via the save tool."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", cfg_path)

    workflow = WorkflowParser.parse(get_onboarding_workflow_path().read_text())
    registry = PrimitiveRegistry()
    register_builtins(registry)
    deps = DefaultDependencies(
        registry=registry,
        tool_registry=workflow.metadata["_inline_tools"],
    )
    executor = WorkflowExecutor(registry, deps=deps)

    generated = json.dumps(
        {"llm_provider": "gemini", "default_model": "gemini-2.0-flash", "project_name": "demo"}
    )
    result = await executor.execute(
        workflow,
        inputs={
            "name": "Alice",
            "provider": "gemini",
            "project_type": "general",
            "apply": True,
            "config_json": generated,
        },
    )

    step_results = result["step_results"]
    assert step_results["generate_config"] is SKIPPED
    assert step_results["show_config"] is SKIPPED
    assert step_results["save_config"]["result"]["saved"] is True

    saved = json.loads(cfg_path.read_text())
    assert saved["llm_provider"] == "gemini"
    assert saved["default_model"] == "gemini-2.0-flash"
    assert saved["project_name"] == "demo"


async def test_preview_renders_form_without_llm() -> None:
    """With no flags, only show_form runs — generate/show are gated out (no LLM)."""
    workflow = WorkflowParser.parse(get_onboarding_workflow_path().read_text())
    registry = PrimitiveRegistry()
    register_builtins(registry)
    deps = DefaultDependencies(
        registry=registry,
        tool_registry=workflow.metadata["_inline_tools"],
    )
    executor = WorkflowExecutor(registry, deps=deps)

    result = await executor.execute(workflow, inputs={})

    step_results = result["step_results"]
    assert step_results["show_form"] is not SKIPPED
    assert step_results["generate_config"] is SKIPPED
    assert step_results["show_config"] is SKIPPED
    # show_form emitted the interactive form surface.
    surfaces = result["metadata"].get("_a2ui_surfaces", [])
    assert any(s.get("surfaceUpdate", {}).get("id") == "onboarding-form" for s in surfaces)
