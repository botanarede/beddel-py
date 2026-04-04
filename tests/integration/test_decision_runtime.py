"""Integration tests for the decision-centric runtime (Story 7.1, Task 5).

Full pipeline: DecidePrimitive + InMemoryDecisionStore + LifecycleHookManager
→ execute decide step → verify Decision in store, hook called, step result
correct, Langfuse tracer integration (mocked), backward-compatible hooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from _helpers import make_context

from beddel.adapters.decision_store import InMemoryDecisionStore
from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.models import Decision, DefaultDependencies, Workflow
from beddel.domain.parser import WorkflowParser
from beddel.domain.ports import ILifecycleHook
from beddel.primitives.decide import DecidePrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config() -> dict[str, Any]:
    return {
        "intent": "Select summarization model",
        "options": ["gpt-4o", "claude-3-opus", "gemini-pro"],
        "chosen": "claude-3-opus",
        "reasoning": "Best quality for long documents",
    }


class _DecisionRecordingHook(ILifecycleHook):
    """Hook that records Decision objects from on_decision."""

    def __init__(self) -> None:
        self.decisions: list[Decision] = []

    async def on_decision(self, decision: Decision) -> None:
        self.decisions.append(decision)


class _OldStyleHook(ILifecycleHook):
    """Hook using the old 3-arg on_decision(str, list, str) signature."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str]] = []

    async def on_decision(self, decision: str, alternatives: list[str], rationale: str) -> None:  # type: ignore[override]
        self.calls.append((decision, alternatives, rationale))


def _make_runtime_context(
    *,
    hooks: LifecycleHookManager | None = None,
    store: InMemoryDecisionStore | None = None,
    tracer: Any | None = None,
) -> Any:
    """Build an ExecutionContext wired with real adapters."""
    ctx = make_context(workflow_id="wf-integration", step_id="step-decide")
    ctx.deps = DefaultDependencies(
        lifecycle_hooks=hooks,
        decision_store=store,
        tracer=tracer,
    )
    return ctx


# ---------------------------------------------------------------------------
# Integration: Full pipeline (subtask 5.3)
# ---------------------------------------------------------------------------


class TestDecisionRuntimePipeline:
    """Full pipeline: primitive → hook → store → result."""

    async def test_full_pipeline_decision_in_store_hook_called_result_correct(self) -> None:
        hook = _DecisionRecordingHook()
        mgr = LifecycleHookManager([hook])
        store = InMemoryDecisionStore()
        ctx = _make_runtime_context(hooks=mgr, store=store)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        # Step result is correct
        assert isinstance(result, dict)
        assert result["intent"] == "Select summarization model"
        assert result["chosen"] == "claude-3-opus"
        assert result["reasoning"] == "Best quality for long documents"
        assert result["options"] == ["gpt-4o", "claude-3-opus", "gemini-pro"]
        assert result["workflow_id"] == "wf-integration"
        assert result["step_id"] == "step-decide"
        assert result["id"]
        assert result["timestamp"]

        # Decision persisted in store
        stored = await store.query(workflow_id="wf-integration")
        assert len(stored) == 1
        assert stored[0].id == result["id"]
        assert stored[0].intent == "Select summarization model"
        assert stored[0].chosen == "claude-3-opus"

        # Hook received the Decision
        assert len(hook.decisions) == 1
        assert hook.decisions[0].id == result["id"]
        assert hook.decisions[0].intent == "Select summarization model"

    async def test_multiple_decisions_accumulate_in_store(self) -> None:
        store = InMemoryDecisionStore()
        mgr = LifecycleHookManager()
        ctx = _make_runtime_context(hooks=mgr, store=store)
        prim = DecidePrimitive()

        await prim.execute(_valid_config(), ctx)
        await prim.execute(
            {
                "intent": "Choose output format",
                "options": ["json", "markdown"],
                "chosen": "json",
                "reasoning": "Structured output needed",
            },
            ctx,
        )

        stored = await store.query(workflow_id="wf-integration")
        assert len(stored) == 2
        intents = {d.intent for d in stored}
        assert intents == {"Select summarization model", "Choose output format"}


# ---------------------------------------------------------------------------
# Integration: Langfuse tracer (mocked) (subtask 5.3 — AC #8)
# ---------------------------------------------------------------------------


class TestLangfuseTracerIntegration:
    """Langfuse tracer receives decision events via duck-typed log_event."""

    async def test_tracer_log_event_called_with_decision_metadata(self) -> None:
        tracer = MagicMock()
        tracer.log_event = MagicMock()
        ctx = _make_runtime_context(tracer=tracer)

        await DecidePrimitive().execute(_valid_config(), ctx)

        tracer.log_event.assert_called_once_with(
            name="decision",
            metadata={
                "intent": "Select summarization model",
                "options": ["gpt-4o", "claude-3-opus", "gemini-pro"],
                "chosen": "claude-3-opus",
                "reasoning": "Best quality for long documents",
            },
        )

    async def test_tracer_without_log_event_is_skipped(self) -> None:
        """Tracer that lacks log_event method is silently skipped."""
        tracer = MagicMock(spec=[])  # no attributes
        ctx = _make_runtime_context(tracer=tracer)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select summarization model"

    async def test_tracer_log_event_error_is_swallowed(self) -> None:
        """Tracer log_event failure does not break the primitive."""
        tracer = MagicMock()
        tracer.log_event = MagicMock(side_effect=RuntimeError("tracer boom"))
        ctx = _make_runtime_context(tracer=tracer)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select summarization model"

    async def test_no_tracer_configured(self) -> None:
        """When tracer is None, primitive still works."""
        ctx = _make_runtime_context(tracer=None)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select summarization model"

    async def test_full_pipeline_with_tracer_hooks_and_store(self) -> None:
        """All three: tracer + hooks + store work together."""
        tracer = MagicMock()
        tracer.log_event = MagicMock()
        hook = _DecisionRecordingHook()
        mgr = LifecycleHookManager([hook])
        store = InMemoryDecisionStore()
        ctx = _make_runtime_context(hooks=mgr, store=store, tracer=tracer)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        # All three fired
        tracer.log_event.assert_called_once()
        assert len(hook.decisions) == 1
        stored = await store.query(workflow_id="wf-integration")
        assert len(stored) == 1
        assert result["id"] == hook.decisions[0].id == stored[0].id


# ---------------------------------------------------------------------------
# Integration: Backward compatibility (subtask 5.5)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Old-style on_decision(str, list, str) hooks work through full pipeline."""

    async def test_old_style_hook_receives_decision_through_primitive(self) -> None:
        """Full path: DecidePrimitive → LifecycleHookManager → old-style hook."""
        old_hook = _OldStyleHook()
        mgr = LifecycleHookManager([old_hook])
        store = InMemoryDecisionStore()
        ctx = _make_runtime_context(hooks=mgr, store=store)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        # Old-style hook received decomposed args
        assert len(old_hook.calls) == 1
        intent, options, reasoning = old_hook.calls[0]
        assert intent == "Select summarization model"
        assert options == ["gpt-4o", "claude-3-opus", "gemini-pro"]
        assert reasoning == "Best quality for long documents"

        # Store still has the full Decision
        stored = await store.query(workflow_id="wf-integration")
        assert len(stored) == 1
        assert stored[0].id == result["id"]

    async def test_mixed_old_and_new_hooks_through_primitive(self) -> None:
        """Both old-style and new-style hooks work in the same pipeline."""
        old_hook = _OldStyleHook()
        new_hook = _DecisionRecordingHook()
        mgr = LifecycleHookManager([old_hook, new_hook])
        ctx = _make_runtime_context(hooks=mgr)

        await DecidePrimitive().execute(_valid_config(), ctx)

        # Old hook got decomposed args
        assert len(old_hook.calls) == 1
        assert old_hook.calls[0][0] == "Select summarization model"

        # New hook got Decision object
        assert len(new_hook.decisions) == 1
        assert new_hook.decisions[0].intent == "Select summarization model"


# ---------------------------------------------------------------------------
# Spec fixture: decision-capture.yaml (subtask 5.4)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VALID_DIR = _REPO_ROOT / "spec" / "fixtures" / "valid"


class TestDecisionCaptureFixture:
    """Spec fixture decision-capture.yaml parses and validates correctly."""

    def test_fixture_parses_to_workflow(self) -> None:
        yaml_str = (_VALID_DIR / "decision-capture.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert isinstance(wf, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = (_VALID_DIR / "decision-capture.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.id == "decision-capture"
        assert wf.name == "Decision Capture Workflow"

    def test_decide_step_present(self) -> None:
        yaml_str = (_VALID_DIR / "decision-capture.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert len(wf.steps) == 1
        step = wf.steps[0]
        assert step.id == "choose-model"
        assert step.primitive == "decide"

    def test_decide_step_config_preserved(self) -> None:
        yaml_str = (_VALID_DIR / "decision-capture.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        config = wf.steps[0].config
        assert config["intent"] == "Select summarization model"
        assert config["options"] == ["gpt-4o", "claude-3-opus", "gemini-pro"]
        assert config["chosen"] == "claude-3-opus"
        assert config["reasoning"] == "Best quality for long documents"

    def test_input_schema_present(self) -> None:
        yaml_str = (_VALID_DIR / "decision-capture.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.input_schema is not None
        assert wf.input_schema["type"] == "object"
