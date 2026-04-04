"""Integration tests for event-driven execution (Story 7.3, Task 5).

Full pipeline: create ExecutionContext with trigger metadata → execute via
EventDrivenExecutionStrategy → verify TriggerEvent injected into context →
verify step results reference trigger payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
    Step,
    TriggerEvent,
    Workflow,
)
from beddel.domain.parser import WorkflowParser
from beddel.domain.strategies.event_driven import (
    EventDrivenExecutionStrategy,
    WebhookTriggerHandler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VALID_DIR = _REPO_ROOT / "spec" / "fixtures" / "valid"


def _make_context(**kwargs: object) -> ExecutionContext:
    defaults: dict[str, object] = {
        "workflow_id": "wf-integration-event",
        "current_step_id": "step-event",
        "deps": DefaultDependencies(),
    }
    defaults.update(kwargs)
    return ExecutionContext(**defaults)  # type: ignore[arg-type]


def _make_workflow(
    steps: list[Step] | None = None,
    metadata: dict[str, object] | None = None,
) -> Workflow:
    return Workflow(
        id="wf-event-integration",
        name="Event Integration Workflow",
        steps=steps or [Step(id="s1", primitive="output-generator")],
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Integration: Full pipeline (subtask 5.3)
# ---------------------------------------------------------------------------


class TestEventDrivenPipeline:
    """Full pipeline: EventDrivenExecutionStrategy with trigger metadata."""

    @pytest.mark.asyncio
    async def test_webhook_trigger_full_pipeline(self) -> None:
        """Execute strategy with webhook trigger metadata, verify TriggerEvent injection."""
        call_order: list[str] = []

        async def _runner(step: Step, ctx: ExecutionContext) -> str:
            call_order.append(step.id)
            return f"result-{step.id}"

        steps = [
            Step(id="process-event", primitive="output-generator", config={"template": "ok"}),
            Step(id="notify", primitive="output-generator", config={"template": "done"}),
        ]
        workflow = _make_workflow(
            steps=steps,
            metadata={"trigger": {"type": "webhook", "config": {"path": "/hooks/deploy"}}},
        )
        context = _make_context()

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, _runner)

        # Verify TriggerEvent was injected
        trigger = context.step_results["_trigger"]
        assert isinstance(trigger, TriggerEvent)
        assert trigger.trigger_type == "webhook"
        assert trigger.timestamp != ""

        # Verify all steps executed in order
        assert call_order == ["process-event", "notify"]

    @pytest.mark.asyncio
    async def test_schedule_trigger_full_pipeline(self) -> None:
        """Execute strategy with schedule trigger metadata, verify TriggerEvent injection."""
        runner = AsyncMock(return_value="scheduled-result")
        workflow = _make_workflow(
            steps=[Step(id="scheduled-task", primitive="output-generator")],
            metadata={"trigger": {"type": "schedule", "config": {"interval": 60}}},
        )
        context = _make_context()

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, runner)

        trigger = context.step_results["_trigger"]
        assert isinstance(trigger, TriggerEvent)
        assert trigger.trigger_type == "schedule"
        runner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pre_injected_trigger_event_preserved(self) -> None:
        """Strategy with pre-injected TriggerEvent (from webhook handler) preserves it."""
        pre_injected = TriggerEvent(
            trigger_type="webhook",
            payload={"event": "push", "repo": "beddel"},
            timestamp="2026-04-04T12:00:00+00:00",
            source="/hooks/deploy",
        )
        runner = AsyncMock(return_value="ok")
        workflow = _make_workflow(
            steps=[Step(id="process", primitive="output-generator")],
            metadata={"trigger": {"type": "webhook", "config": {"path": "/hooks/deploy"}}},
        )
        context = _make_context()
        context.step_results["_trigger"] = pre_injected

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, runner)

        # Pre-injected event must be preserved, not overwritten
        assert context.step_results["_trigger"] is pre_injected
        assert context.step_results["_trigger"].payload == {"event": "push", "repo": "beddel"}
        runner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_webhook_handler_to_strategy_pipeline(self) -> None:
        """Webhook handler → strategy pipeline: register, dispatch, execute."""
        # 1. Set up webhook handler with a callback that runs the strategy
        executed_events: list[TriggerEvent] = []

        async def _on_webhook(event: TriggerEvent) -> None:
            executed_events.append(event)

        app = MagicMock()
        registered_handler = None

        def _capture_decorator(path: str):  # noqa: ANN202
            def _decorator(fn):  # noqa: ANN001, ANN202
                nonlocal registered_handler
                registered_handler = fn
                return fn

            return _decorator

        app.post = _capture_decorator

        # 2. Register webhook
        handler = WebhookTriggerHandler()
        handler.register(app, "wf-deploy", {"path": "/hooks/deploy"}, _on_webhook)
        assert registered_handler is not None

        # 3. Simulate webhook dispatch
        body = {"action": "deploy", "version": "1.2.3"}
        result = await registered_handler(body)
        assert result == {"status": "accepted"}

        # 4. Verify TriggerEvent was created and dispatched
        assert len(executed_events) == 1
        event = executed_events[0]
        assert event.trigger_type == "webhook"
        assert event.payload == {"action": "deploy", "version": "1.2.3"}
        assert event.source == "/hooks/deploy"

        # 5. Now run the strategy with this event pre-injected
        runner = AsyncMock(return_value="deployed")
        workflow = _make_workflow(
            steps=[Step(id="deploy", primitive="output-generator")],
            metadata={"trigger": {"type": "webhook", "config": {"path": "/hooks/deploy"}}},
        )
        context = _make_context()
        context.step_results["_trigger"] = event

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, runner)

        # Event preserved through strategy execution
        assert context.step_results["_trigger"] is event
        runner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_step_results_accessible_after_execution(self) -> None:
        """Step results are populated alongside trigger event after execution."""
        results_seen: dict[str, Any] = {}

        async def _runner(step: Step, ctx: ExecutionContext) -> str:
            # Capture what's in step_results at execution time
            results_seen[step.id] = dict(ctx.step_results)
            ctx.step_results[step.id] = f"output-{step.id}"
            return f"output-{step.id}"

        steps = [
            Step(id="step-a", primitive="output-generator"),
            Step(id="step-b", primitive="output-generator"),
        ]
        workflow = _make_workflow(
            steps=steps,
            metadata={"trigger": {"type": "webhook", "config": {"path": "/hooks/test"}}},
        )
        context = _make_context()

        await EventDrivenExecutionStrategy().execute(workflow, context, _runner)

        # step-a should have seen _trigger but no step results yet
        assert "_trigger" in results_seen["step-a"]
        assert isinstance(results_seen["step-a"]["_trigger"], TriggerEvent)

        # step-b should have seen _trigger AND step-a's result
        assert "_trigger" in results_seen["step-b"]
        assert results_seen["step-b"]["step-a"] == "output-step-a"


# ---------------------------------------------------------------------------
# Spec fixture: event-driven-webhook.yaml (subtask 5.1)
# ---------------------------------------------------------------------------


class TestEventDrivenWebhookFixture:
    """Spec fixture event-driven-webhook.yaml parses and validates."""

    def test_fixture_parses_to_workflow(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-webhook.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert isinstance(wf, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-webhook.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.id == "event-driven-webhook-demo"
        assert wf.name == "Event-Driven Webhook Demo"

    def test_trigger_metadata_present(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-webhook.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        trigger = wf.metadata["trigger"]
        assert trigger["type"] == "webhook"
        assert trigger["config"]["path"] == "/hooks/deploy"

    def test_step_references_trigger_payload(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-webhook.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert len(wf.steps) == 1
        step = wf.steps[0]
        assert step.id == "process-event"
        assert step.primitive == "output-generator"
        assert "$stepResult._trigger.payload" in step.config["template"]


# ---------------------------------------------------------------------------
# Spec fixture: event-driven-schedule.yaml (subtask 5.2)
# ---------------------------------------------------------------------------


class TestEventDrivenScheduleFixture:
    """Spec fixture event-driven-schedule.yaml parses and validates."""

    def test_fixture_parses_to_workflow(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-schedule.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert isinstance(wf, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-schedule.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.id == "event-driven-schedule-demo"
        assert wf.name == "Event-Driven Schedule Demo"

    def test_trigger_metadata_present(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-schedule.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        trigger = wf.metadata["trigger"]
        assert trigger["type"] == "schedule"
        assert trigger["config"]["interval"] == 60

    def test_step_present(self) -> None:
        yaml_str = (_VALID_DIR / "event-driven-schedule.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert len(wf.steps) == 1
        step = wf.steps[0]
        assert step.id == "scheduled-task"
        assert step.primitive == "output-generator"
