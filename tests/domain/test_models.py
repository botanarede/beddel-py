"""Unit tests for beddel.domain.models module."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from beddel.domain.models import (
    BeddelEvent,
    EventType,
    ExecutionContext,
    ExecutionStrategy,
    RetryConfig,
    Step,
    StrategyType,
    Workflow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_step(**overrides: object) -> dict:
    """Return the minimal valid Step payload, with optional overrides."""
    base: dict = {"id": "s1", "primitive": "llm"}
    base.update(overrides)
    return base


def _minimal_workflow(**overrides: object) -> dict:
    """Return the minimal valid Workflow payload, with optional overrides."""
    base: dict = {
        "id": "wf1",
        "name": "Test Workflow",
        "steps": [_minimal_step()],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class TestWorkflow:
    """Tests for the Workflow model."""

    def test_creation_with_required_fields(self) -> None:
        wf = Workflow(**_minimal_workflow())

        assert wf.id == "wf1"
        assert wf.name == "Test Workflow"
        assert len(wf.steps) == 1

    def test_defaults_populated(self) -> None:
        wf = Workflow(**_minimal_workflow())

        assert wf.description == ""
        assert wf.version == "1.0"
        assert wf.input_schema is None
        assert wf.metadata == {}

    def test_custom_metadata_and_input_schema(self) -> None:
        schema = {"type": "object", "properties": {"prompt": {"type": "string"}}}
        wf = Workflow(
            **_minimal_workflow(
                description="A test",
                version="2.0",
                input_schema=schema,
                metadata={"author": "test"},
            )
        )

        assert wf.description == "A test"
        assert wf.version == "2.0"
        assert wf.input_schema == schema
        assert wf.metadata == {"author": "test"}

    def test_multiple_steps(self) -> None:
        steps = [_minimal_step(id="s1"), _minimal_step(id="s2")]
        wf = Workflow(**_minimal_workflow(steps=steps))

        assert len(wf.steps) == 2
        assert wf.steps[1].id == "s2"


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


class TestStep:
    """Tests for the Step model."""

    def test_creation_with_required_fields(self) -> None:
        step = Step(**_minimal_step())

        assert step.id == "s1"
        assert step.primitive == "llm"

    def test_defaults(self) -> None:
        step = Step(**_minimal_step())

        assert step.config == {}
        assert step.if_condition is None
        assert step.then_steps is None
        assert step.else_steps is None
        assert step.timeout is None
        assert step.stream is False
        assert step.parallel is False
        assert step.metadata == {}

    def test_execution_strategy_default_is_fail(self) -> None:
        step = Step(**_minimal_step())

        assert step.execution_strategy.type == StrategyType.FAIL

    def test_alias_if_then_else(self) -> None:
        """Aliases 'if', 'then', 'else' populate the corresponding fields."""
        data = {
            "id": "branch",
            "primitive": "llm",
            "if": "ctx.score > 0.5",
            "then": [_minimal_step(id="t1")],
            "else": [_minimal_step(id="e1")],
        }
        step = Step(**data)

        assert step.if_condition == "ctx.score > 0.5"
        assert step.then_steps is not None
        assert len(step.then_steps) == 1
        assert step.then_steps[0].id == "t1"
        assert step.else_steps is not None
        assert step.else_steps[0].id == "e1"

    def test_field_names_also_work(self) -> None:
        """Fields can be set via their Python names too (populate_by_name)."""
        step = Step(
            id="s1",
            primitive="llm",
            if_condition="true",
            then_steps=[Step(**_minimal_step(id="t1"))],
            else_steps=[Step(**_minimal_step(id="e1"))],
        )

        assert step.if_condition == "true"
        assert step.then_steps is not None
        assert step.then_steps[0].id == "t1"

    def test_nested_then_else_steps(self) -> None:
        inner = _minimal_step(id="inner")
        outer = {
            "id": "outer",
            "primitive": "llm",
            "then": [{"id": "mid", "primitive": "llm", "then": [inner]}],
        }
        step = Step(**outer)

        assert step.then_steps is not None
        assert step.then_steps[0].then_steps is not None
        assert step.then_steps[0].then_steps[0].id == "inner"

    def test_custom_config_and_metadata(self) -> None:
        step = Step(
            **_minimal_step(
                config={"model": "gpt-4"},
                metadata={"owner": "team-a"},
                timeout=30.0,
                stream=True,
                parallel=True,
            )
        )

        assert step.config == {"model": "gpt-4"}
        assert step.metadata == {"owner": "team-a"}
        assert step.timeout == 30.0
        assert step.stream is True
        assert step.parallel is True


# ---------------------------------------------------------------------------
# ExecutionStrategy
# ---------------------------------------------------------------------------


class TestExecutionStrategy:
    """Tests for the ExecutionStrategy model."""

    def test_default_type_is_fail(self) -> None:
        strategy = ExecutionStrategy()

        assert strategy.type == StrategyType.FAIL
        assert strategy.retry is None
        assert strategy.fallback_step is None

    @pytest.mark.parametrize("stype", list(StrategyType), ids=[s.value for s in StrategyType])
    def test_all_strategy_types(self, stype: StrategyType) -> None:
        strategy = ExecutionStrategy(type=stype)

        assert strategy.type == stype

    def test_with_retry_config(self) -> None:
        retry = RetryConfig(max_attempts=5)
        strategy = ExecutionStrategy(type=StrategyType.RETRY, retry=retry)

        assert strategy.retry is not None
        assert strategy.retry.max_attempts == 5

    def test_with_fallback_step(self) -> None:
        fallback = Step(**_minimal_step(id="fallback"))
        strategy = ExecutionStrategy(type=StrategyType.FALLBACK, fallback_step=fallback)

        assert strategy.fallback_step is not None
        assert strategy.fallback_step.id == "fallback"


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------


class TestRetryConfig:
    """Tests for the RetryConfig model."""

    def test_defaults(self) -> None:
        cfg = RetryConfig()

        assert cfg.max_attempts == 3
        assert cfg.backoff_base == 2.0
        assert cfg.backoff_max == 60.0
        assert cfg.jitter is True

    def test_custom_values(self) -> None:
        cfg = RetryConfig(max_attempts=10, backoff_base=1.5, backoff_max=120.0, jitter=False)

        assert cfg.max_attempts == 10
        assert cfg.backoff_base == 1.5
        assert cfg.backoff_max == 120.0
        assert cfg.jitter is False


# ---------------------------------------------------------------------------
# ExecutionContext
# ---------------------------------------------------------------------------


class TestExecutionContext:
    """Tests for the ExecutionContext model."""

    def test_creation_with_workflow_id(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")

        assert ctx.workflow_id == "wf-1"

    def test_defaults(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")

        assert ctx.inputs == {}
        assert ctx.step_results == {}
        assert ctx.metadata == {}
        assert ctx.current_step_id is None

    def test_arbitrary_types_allowed(self) -> None:
        """ConfigDict(arbitrary_types_allowed=True) is set."""
        assert ExecutionContext.model_config.get("arbitrary_types_allowed") is True

    def test_custom_values(self) -> None:
        ctx = ExecutionContext(
            workflow_id="wf-2",
            inputs={"prompt": "hello"},
            step_results={"s1": "ok"},
            metadata={"run": 1},
            current_step_id="s1",
        )

        assert ctx.inputs == {"prompt": "hello"}
        assert ctx.step_results == {"s1": "ok"}
        assert ctx.metadata == {"run": 1}
        assert ctx.current_step_id == "s1"


# ---------------------------------------------------------------------------
# BeddelEvent
# ---------------------------------------------------------------------------


class TestBeddelEvent:
    """Tests for the BeddelEvent model."""

    def test_creation_with_event_type(self) -> None:
        event = BeddelEvent(event_type=EventType.STEP_START)

        assert event.event_type == EventType.STEP_START

    def test_default_timestamp_is_float(self) -> None:
        before = time.time()
        event = BeddelEvent(event_type=EventType.WORKFLOW_START)
        after = time.time()

        assert isinstance(event.timestamp, float)
        assert before <= event.timestamp <= after

    def test_defaults(self) -> None:
        event = BeddelEvent(event_type=EventType.ERROR)

        assert event.step_id is None
        assert event.data == {}

    @pytest.mark.parametrize("etype", list(EventType), ids=[e.value for e in EventType])
    def test_all_event_types(self, etype: EventType) -> None:
        event = BeddelEvent(event_type=etype)

        assert event.event_type == etype

    def test_custom_data_and_step_id(self) -> None:
        event = BeddelEvent(
            event_type=EventType.TEXT_CHUNK,
            step_id="s1",
            data={"chunk": "hello"},
        )

        assert event.step_id == "s1"
        assert event.data == {"chunk": "hello"}


# ---------------------------------------------------------------------------
# StrategyType & EventType enums
# ---------------------------------------------------------------------------


class TestStrategyTypeEnum:
    """Tests for the StrategyType string enum."""

    def test_values(self) -> None:
        assert StrategyType.FAIL == "fail"
        assert StrategyType.SKIP == "skip"
        assert StrategyType.RETRY == "retry"
        assert StrategyType.FALLBACK == "fallback"
        assert StrategyType.DELEGATE == "delegate"

    def test_member_count(self) -> None:
        assert len(StrategyType) == 5


class TestEventTypeEnum:
    """Tests for the EventType string enum."""

    def test_values(self) -> None:
        assert EventType.WORKFLOW_START == "workflow_start"
        assert EventType.WORKFLOW_END == "workflow_end"
        assert EventType.STEP_START == "step_start"
        assert EventType.STEP_END == "step_end"
        assert EventType.LLM_START == "llm_start"
        assert EventType.LLM_END == "llm_end"
        assert EventType.TEXT_CHUNK == "text_chunk"
        assert EventType.ERROR == "error"
        assert EventType.RETRY == "retry"

    def test_member_count(self) -> None:
        assert len(EventType) == 9


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class TestValidationErrors:
    """Tests that Pydantic raises ValidationError for invalid data."""

    def test_workflow_missing_id(self) -> None:
        with pytest.raises(ValidationError):
            Workflow(name="no-id", steps=[Step(**_minimal_step())])  # type: ignore[call-arg]

    def test_workflow_missing_name(self) -> None:
        with pytest.raises(ValidationError):
            Workflow(id="wf1", steps=[Step(**_minimal_step())])  # type: ignore[call-arg]

    def test_workflow_missing_steps(self) -> None:
        with pytest.raises(ValidationError):
            Workflow(id="wf1", name="no-steps")  # type: ignore[call-arg]

    def test_step_missing_id(self) -> None:
        with pytest.raises(ValidationError):
            Step(primitive="llm")  # type: ignore[call-arg]

    def test_step_missing_primitive(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1")  # type: ignore[call-arg]

    def test_execution_context_missing_workflow_id(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionContext()  # type: ignore[call-arg]

    def test_beddel_event_missing_event_type(self) -> None:
        with pytest.raises(ValidationError):
            BeddelEvent()  # type: ignore[call-arg]

    def test_workflow_wrong_type_for_steps(self) -> None:
        with pytest.raises(ValidationError):
            Workflow(id="wf1", name="bad", steps="not-a-list")  # type: ignore[arg-type]

    def test_step_wrong_type_for_timeout(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", primitive="llm", timeout="not-a-float")  # type: ignore[arg-type]

    def test_strategy_wrong_type_for_type_field(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionStrategy(type="invalid_strategy")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestAllExports:
    """Tests that __all__ contains all expected model names."""

    def test_all_contains_expected_names(self) -> None:
        from beddel.domain import models

        expected = {
            "BeddelEvent",
            "EventType",
            "ExecutionContext",
            "ExecutionStrategy",
            "InterruptibleContext",
            "RetryConfig",
            "Step",
            "StrategyType",
            "Workflow",
        }
        assert set(models.__all__) == expected
