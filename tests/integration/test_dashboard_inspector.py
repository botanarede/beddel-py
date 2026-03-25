"""Unit tests for WorkflowInspector (Story D1.3, Task 2)."""

from __future__ import annotations

from typing import Any

from beddel.domain.models import Step, Workflow
from beddel.integrations.dashboard.inspector import WorkflowInspector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(
    wf_id: str = "wf-1",
    name: str = "Test Workflow",
    description: str = "A test workflow",
    version: str = "1.0",
    steps: list[Step] | None = None,
    input_schema: dict[str, Any] | None = None,
) -> Workflow:
    """Create a Workflow with sensible defaults."""
    return Workflow(
        id=wf_id,
        name=name,
        description=description,
        version=version,
        steps=steps or [Step(id="s1", primitive="llm", config={"model": "gpt-4"})],
        input_schema=input_schema,
    )


# ---------------------------------------------------------------------------
# list_workflows tests
# ---------------------------------------------------------------------------


class TestListWorkflows:
    """Tests for WorkflowInspector.list_workflows()."""

    def test_empty_inspector(self) -> None:
        inspector = WorkflowInspector({})
        assert inspector.list_workflows() == []

    def test_single_workflow(self) -> None:
        wf = _make_workflow()
        inspector = WorkflowInspector({"wf-1": wf})
        result = inspector.list_workflows()
        assert len(result) == 1
        assert result[0]["id"] == "wf-1"
        assert result[0]["name"] == "Test Workflow"
        assert result[0]["description"] == "A test workflow"
        assert result[0]["version"] == "1.0"
        assert result[0]["step_count"] == 1

    def test_multiple_workflows(self) -> None:
        wf1 = _make_workflow(wf_id="a", name="Alpha")
        wf2 = _make_workflow(
            wf_id="b",
            name="Beta",
            steps=[
                Step(id="s1", primitive="llm", config={}),
                Step(id="s2", primitive="chat", config={}),
            ],
        )
        inspector = WorkflowInspector({"a": wf1, "b": wf2})
        result = inspector.list_workflows()
        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert ids == {"a", "b"}

    def test_step_count_reflects_top_level_steps(self) -> None:
        wf = _make_workflow(
            steps=[
                Step(id="s1", primitive="llm", config={}),
                Step(id="s2", primitive="chat", config={}),
                Step(id="s3", primitive="output-generator", config={}),
            ],
        )
        inspector = WorkflowInspector({"wf-1": wf})
        result = inspector.list_workflows()
        assert result[0]["step_count"] == 3


# ---------------------------------------------------------------------------
# get_workflow_detail tests
# ---------------------------------------------------------------------------


class TestGetWorkflowDetail:
    """Tests for WorkflowInspector.get_workflow_detail()."""

    def test_get_existing(self) -> None:
        wf = _make_workflow(input_schema={"type": "object"})
        inspector = WorkflowInspector({"wf-1": wf})
        result = inspector.get_workflow_detail("wf-1")
        assert result is not None
        assert result["id"] == "wf-1"
        assert result["name"] == "Test Workflow"
        assert "steps" in result
        assert result["input_schema"] == {"type": "object"}

    def test_get_missing_returns_none(self) -> None:
        inspector = WorkflowInspector({})
        assert inspector.get_workflow_detail("nonexistent") is None

    def test_detail_includes_metadata(self) -> None:
        wf = _make_workflow()
        wf.metadata["author"] = "test"
        inspector = WorkflowInspector({"wf-1": wf})
        result = inspector.get_workflow_detail("wf-1")
        assert result is not None
        assert result["metadata"]["author"] == "test"

    def test_detail_steps_are_serialized(self) -> None:
        wf = _make_workflow()
        inspector = WorkflowInspector({"wf-1": wf})
        result = inspector.get_workflow_detail("wf-1")
        assert result is not None
        assert isinstance(result["steps"], list)
        assert result["steps"][0]["id"] == "s1"
