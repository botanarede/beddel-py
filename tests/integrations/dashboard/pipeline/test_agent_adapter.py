"""Tests for AgentPipelineAdapter base class — event translation and health."""

from __future__ import annotations

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult
from beddel.integrations.dashboard.pipeline.agent_adapter import AgentPipelineAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    *,
    exit_code: int = 0,
    output: str = "test output",
    files_changed: list[str] | None = None,
    usage: dict[str, object] | None = None,
) -> AgentResult:
    return AgentResult(
        exit_code=exit_code,
        output=output,
        events=[],
        files_changed=files_changed or [],
        usage=usage or {"prompt_tokens": 100},
        agent_id="test-agent",
    )


# ---------------------------------------------------------------------------
# TestAgentPipelineAdapterTranslateResult
# ---------------------------------------------------------------------------


class TestAgentPipelineAdapterTranslateResult:
    """translate_result() produces the correct event sequence."""

    def test_event_sequence_no_files(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        result = _make_result()

        events = adapter.translate_result(result)

        assert len(events) == 3
        assert events[0].event_type == "pipeline_stage_changed"
        assert events[0].agent_id == "a1"
        assert events[0].payload["stage"] == "agent_execution"
        assert events[0].payload["backend"] == "test"

        assert events[1].event_type == "task_completed"
        assert events[1].payload["output"] == "test output"
        assert events[1].payload["exit_code"] == 0

        assert events[2].event_type == "step_end"
        assert events[2].payload["usage"] == {"prompt_tokens": 100}
        assert events[2].payload["exit_code"] == 0

    def test_event_sequence_with_files(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        result = _make_result(files_changed=["src/foo.py", "src/bar.py"])

        events = adapter.translate_result(result)

        # pipeline_stage_changed, task_completed, 2× agent_file_changed, step_end
        assert len(events) == 5
        types = [e.event_type for e in events]
        assert types == [
            "pipeline_stage_changed",
            "task_completed",
            "agent_file_changed",
            "agent_file_changed",
            "step_end",
        ]
        assert events[2].payload["file"] == "src/foo.py"
        assert events[3].payload["file"] == "src/bar.py"

    def test_output_truncated_to_500(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        long_output = "x" * 1000
        result = _make_result(output=long_output)

        events = adapter.translate_result(result)

        task_event = events[1]
        assert len(task_event.payload["output"]) == 500


# ---------------------------------------------------------------------------
# TestAgentPipelineAdapterTranslateError
# ---------------------------------------------------------------------------


class TestAgentPipelineAdapterTranslateError:
    """translate_error() produces a gate_failed event."""

    def test_gate_failed_event(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")
        error = AgentError(
            code="BEDDEL-AGENT-701",
            message="test error",
            details={"key": "value"},
        )

        event = adapter.translate_error(error)

        assert event.event_type == "gate_failed"
        assert event.agent_id == "a1"
        assert event.payload["code"] == "BEDDEL-AGENT-701"
        assert event.payload["message"] == "test error"
        assert event.payload["details"] == {"key": "value"}


# ---------------------------------------------------------------------------
# TestAgentPipelineAdapterHealth
# ---------------------------------------------------------------------------


class TestAgentPipelineAdapterHealth:
    """health() returns correct status after mark_active/mark_inactive."""

    def test_initial_status_disconnected(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")

        status = adapter.health()

        assert status.agent_id == "a1"
        assert status.backend == "test"
        assert status.status == "disconnected"
        assert status.last_activity is None

    def test_mark_active(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")

        adapter.mark_active()
        status = adapter.health()

        assert status.status == "connected"
        assert status.last_activity is not None

    def test_mark_inactive(self) -> None:
        adapter = AgentPipelineAdapter(agent_id="a1", backend="test")

        adapter.mark_active()
        adapter.mark_inactive()
        status = adapter.health()

        assert status.status == "disconnected"
        assert status.last_activity is not None
