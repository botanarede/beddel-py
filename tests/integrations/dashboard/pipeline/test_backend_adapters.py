"""Tests for backend-specific pipeline adapters (OpenClaw, Claude, Codex)."""

from __future__ import annotations

from beddel.integrations.dashboard.pipeline.claude_pipeline import (
    ClaudePipelineAdapter,
)
from beddel.integrations.dashboard.pipeline.codex_pipeline import (
    CodexPipelineAdapter,
)
from beddel.integrations.dashboard.pipeline.openclaw_pipeline import (
    OpenClawPipelineAdapter,
)

# ---------------------------------------------------------------------------
# TestOpenClawPipelineAdapterTranslateStreamEvent
# ---------------------------------------------------------------------------


class TestOpenClawPipelineAdapterTranslateStreamEvent:
    """OpenClaw Gateway single-event mapping."""

    def test_complete_event(self) -> None:
        adapter = OpenClawPipelineAdapter(agent_id="oc1", gateway_url="http://gw:8080")
        event = {"type": "complete", "output": "done", "exit_code": 0}

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "task_completed"
        assert result.agent_id == "oc1"
        assert result.payload["output"] == "done"
        assert result.payload["exit_code"] == 0

    def test_unknown_event_returns_none(self) -> None:
        adapter = OpenClawPipelineAdapter(agent_id="oc1", gateway_url="http://gw:8080")

        result = adapter.translate_stream_event({"type": "partial"})

        assert result is None

    def test_output_truncated(self) -> None:
        adapter = OpenClawPipelineAdapter(agent_id="oc1", gateway_url="http://gw:8080")
        event = {"type": "complete", "output": "x" * 1000, "exit_code": 0}

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert len(result.payload["output"]) == 500

    def test_gateway_url_property(self) -> None:
        adapter = OpenClawPipelineAdapter(agent_id="oc1", gateway_url="http://gw:8080")

        assert adapter.gateway_url == "http://gw:8080"


# ---------------------------------------------------------------------------
# TestClaudePipelineAdapterTranslateStreamEvent
# ---------------------------------------------------------------------------


class TestClaudePipelineAdapterTranslateStreamEvent:
    """Claude streaming event mapping."""

    def test_content_block_delta(self) -> None:
        adapter = ClaudePipelineAdapter(agent_id="cl1")
        event = {
            "type": "content_block_delta",
            "delta": {"text": "hello world"},
        }

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "task_completed"
        assert result.payload["output"] == "hello world"
        assert result.payload["partial"] is True

    def test_tool_use_file_tool(self) -> None:
        adapter = ClaudePipelineAdapter(agent_id="cl1")
        event = {
            "type": "tool_use",
            "name": "file_write",
            "input": {"path": "src/main.py"},
        }

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "agent_file_changed"
        assert result.payload["file"] == "src/main.py"
        assert result.payload["tool"] == "file_write"

    def test_tool_use_non_file_tool_returns_none(self) -> None:
        adapter = ClaudePipelineAdapter(agent_id="cl1")
        event = {
            "type": "tool_use",
            "name": "web_search",
            "input": {"query": "test"},
        }

        result = adapter.translate_stream_event(event)

        assert result is None

    def test_message_stop(self) -> None:
        adapter = ClaudePipelineAdapter(agent_id="cl1")
        event = {"type": "message_stop"}

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "step_end"
        assert result.agent_id == "cl1"

    def test_unknown_event_returns_none(self) -> None:
        adapter = ClaudePipelineAdapter(agent_id="cl1")

        result = adapter.translate_stream_event({"type": "ping"})

        assert result is None


# ---------------------------------------------------------------------------
# TestCodexPipelineAdapterTranslateStreamEvent
# ---------------------------------------------------------------------------


class TestCodexPipelineAdapterTranslateStreamEvent:
    """Codex JSONL event mapping."""

    def test_thread_started(self) -> None:
        adapter = CodexPipelineAdapter(agent_id="cx1")
        event = {"type": "thread.started"}

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "pipeline_stage_changed"
        assert result.payload["stage"] == "agent_execution"
        assert result.payload["backend"] == "codex"

    def test_item_completed(self) -> None:
        adapter = CodexPipelineAdapter(agent_id="cx1")
        event = {
            "type": "item.completed",
            "output": [{"text": "result A"}, {"text": " result B"}],
        }

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "task_completed"
        assert result.payload["output"] == "result A result B"

    def test_turn_completed(self) -> None:
        adapter = CodexPipelineAdapter(agent_id="cx1")
        event = {
            "type": "turn.completed",
            "usage": {"prompt_tokens": 50, "completion_tokens": 30},
        }

        result = adapter.translate_stream_event(event)

        assert result is not None
        assert result.event_type == "step_end"
        assert result.payload["usage"]["prompt_tokens"] == 50

    def test_unknown_event_returns_none(self) -> None:
        adapter = CodexPipelineAdapter(agent_id="cx1")

        result = adapter.translate_stream_event({"type": "heartbeat"})

        assert result is None
