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
# Step — tags field
# ---------------------------------------------------------------------------


class TestStepTags:
    """Tests for the Step.tags field (step-level tagging)."""

    def test_step_tags_defaults_to_empty_list(self) -> None:
        """Step created without tags has an empty list."""
        # Arrange / Act
        step = Step(**_minimal_step())

        # Assert
        assert step.tags == []

    def test_step_tags_stores_values(self) -> None:
        """Step created with explicit tags stores and returns them."""
        # Arrange / Act
        step = Step(**_minimal_step(tags=["generate", "evaluate"]))

        # Assert
        assert step.tags == ["generate", "evaluate"]

    def test_step_tags_preserved_through_serialization(self) -> None:
        """Tags survive a model_dump → model_validate round-trip."""
        # Arrange
        step = Step(**_minimal_step(tags=["generate", "evaluate"]))

        # Act
        data = step.model_dump()
        restored = Step.model_validate(data)

        # Assert
        assert restored.tags == ["generate", "evaluate"]


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
# DefaultDependencies
# ---------------------------------------------------------------------------


class TestDefaultDependencies:
    """Tests for the DefaultDependencies dependency container."""

    def test_tracer_defaults_to_none(self) -> None:
        """DefaultDependencies without tracer returns None."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()

        assert deps.tracer is None

    def test_tracer_stores_and_returns_instance(self) -> None:
        """DefaultDependencies(tracer=NoOpTracer()) stores and returns it."""
        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import NoOpTracer

        tracer = NoOpTracer()
        deps = DefaultDependencies(tracer=tracer)

        assert deps.tracer is tracer

    def test_tracer_protocol_compliance(self) -> None:
        """DefaultDependencies with tracer satisfies ExecutionDependencies protocol."""
        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import NoOpTracer

        deps = DefaultDependencies(tracer=NoOpTracer())

        # Structural subtyping — isinstance won't work with Protocol at runtime,
        # but we can verify the attribute exists and has the right type.
        assert hasattr(deps, "tracer")
        assert isinstance(deps.tracer, NoOpTracer)

    def test_tracer_explicit_none_same_as_default(self) -> None:
        """Passing tracer=None explicitly behaves identically to omitting it."""
        from beddel.domain.models import DefaultDependencies

        deps_default = DefaultDependencies()
        deps_explicit = DefaultDependencies(tracer=None)

        assert deps_default.tracer is None
        assert deps_explicit.tracer is None

    def test_tracer_with_custom_itracer_subclass(self) -> None:
        """A custom ITracer subclass is stored and returned correctly."""
        from typing import Any

        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import ITracer

        class _StubTracer(ITracer):
            """Minimal custom tracer for testing."""

            def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
                return {"name": name}

            def end_span(self, span: Any, attributes: dict[str, Any] | None = None) -> None:
                pass

        tracer = _StubTracer()
        deps = DefaultDependencies(tracer=tracer)

        assert deps.tracer is tracer
        assert isinstance(deps.tracer, ITracer)

    def test_tracer_accessible_via_execution_context(self) -> None:
        """Tracer is reachable through ExecutionContext.deps.tracer."""
        from beddel.domain.models import DefaultDependencies, ExecutionContext
        from beddel.domain.ports import NoOpTracer

        tracer = NoOpTracer()
        ctx = ExecutionContext(
            workflow_id="wf-test",
            deps=DefaultDependencies(tracer=tracer),
        )

        assert ctx.deps.tracer is tracer

    def test_tracer_none_via_execution_context(self) -> None:
        """ExecutionContext with default deps has tracer=None."""
        from beddel.domain.models import ExecutionContext

        ctx = ExecutionContext(workflow_id="wf-test")

        assert ctx.deps.tracer is None

    def test_tracer_does_not_affect_other_properties(self) -> None:
        """Setting tracer leaves all other dependency defaults unchanged."""
        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import NoOpTracer

        deps = DefaultDependencies(tracer=NoOpTracer())

        assert deps.llm_provider is None
        assert deps.lifecycle_hooks is None
        assert deps.execution_strategy is None
        assert deps.delegate_model == "gpt-4o-mini"
        assert deps.workflow_loader is None
        assert deps.registry is None
        assert deps.tool_registry is None

    def test_lifecycle_hooks_accepts_ihookmanager(self) -> None:
        """DefaultDependencies accepts IHookManager and returns it from property."""
        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import IHookManager, ILifecycleHook

        class FakeHookManager(IHookManager):
            async def add_hook(self, hook: ILifecycleHook) -> None:
                pass

            async def remove_hook(self, hook: ILifecycleHook) -> None:
                pass

        manager = FakeHookManager()
        deps = DefaultDependencies(lifecycle_hooks=manager)

        assert deps.lifecycle_hooks is manager

    def test_lifecycle_hooks_defaults_to_none(self) -> None:
        """DefaultDependencies without lifecycle_hooks returns None."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()

        assert deps.lifecycle_hooks is None

    def test_lifecycle_hooks_explicit_none(self) -> None:
        """DefaultDependencies(lifecycle_hooks=None) stores None."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies(lifecycle_hooks=None)

        assert deps.lifecycle_hooks is None

    # -- agent_adapter tests --

    def test_agent_adapter_defaults_to_none(self) -> None:
        """DefaultDependencies without agent_adapter returns None."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()

        assert deps.agent_adapter is None

    def test_agent_adapter_stores_and_returns_instance(self) -> None:
        """DefaultDependencies(agent_adapter=mock) stores and returns it."""
        from unittest.mock import AsyncMock

        from beddel.domain.models import DefaultDependencies

        mock_adapter = AsyncMock()
        deps = DefaultDependencies(agent_adapter=mock_adapter)

        assert deps.agent_adapter is mock_adapter

    def test_agent_adapter_explicit_none(self) -> None:
        """Passing agent_adapter=None explicitly behaves identically to omitting it."""
        from beddel.domain.models import DefaultDependencies

        deps_default = DefaultDependencies()
        deps_explicit = DefaultDependencies(agent_adapter=None)

        assert deps_default.agent_adapter is None
        assert deps_explicit.agent_adapter is None

    # -- agent_registry tests --

    def test_agent_registry_defaults_to_none(self) -> None:
        """DefaultDependencies without agent_registry returns None."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()

        assert deps.agent_registry is None

    def test_agent_registry_stores_and_returns_dict(self) -> None:
        """DefaultDependencies(agent_registry={...}) stores and returns the dict."""
        from unittest.mock import AsyncMock

        from beddel.domain.models import DefaultDependencies

        mock_codex = AsyncMock()
        mock_claude = AsyncMock()
        registry = {"codex": mock_codex, "claude": mock_claude}
        deps = DefaultDependencies(agent_registry=registry)

        assert deps.agent_registry is registry
        assert deps.agent_registry["codex"] is mock_codex
        assert deps.agent_registry["claude"] is mock_claude

    def test_agent_registry_explicit_none(self) -> None:
        """Passing agent_registry=None explicitly behaves identically to omitting it."""
        from beddel.domain.models import DefaultDependencies

        deps_default = DefaultDependencies()
        deps_explicit = DefaultDependencies(agent_registry=None)

        assert deps_default.agent_registry is None
        assert deps_explicit.agent_registry is None

    # -- backward compatibility --

    def test_agent_params_backward_compatible(self) -> None:
        """Existing DefaultDependencies() calls without agent params still work."""
        from beddel.domain.models import DefaultDependencies
        from beddel.domain.ports import NoOpTracer

        deps = DefaultDependencies(
            delegate_model="gpt-4o",
            tracer=NoOpTracer(),
        )

        assert deps.delegate_model == "gpt-4o"
        assert deps.tracer is not None
        assert deps.agent_adapter is None
        assert deps.agent_registry is None

    def test_agent_adapter_does_not_affect_other_properties(self) -> None:
        """Setting agent_adapter leaves all other dependency defaults unchanged."""
        from unittest.mock import AsyncMock

        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies(agent_adapter=AsyncMock())

        assert deps.llm_provider is None
        assert deps.lifecycle_hooks is None
        assert deps.execution_strategy is None
        assert deps.delegate_model == "gpt-4o-mini"
        assert deps.workflow_loader is None
        assert deps.registry is None
        assert deps.tool_registry is None
        assert deps.tracer is None
        assert deps.agent_registry is None

    # -- Protocol property existence --

    def test_execution_dependencies_protocol_has_agent_properties(self) -> None:
        """ExecutionDependencies Protocol defines agent_adapter and agent_registry."""
        from beddel.domain.ports import ExecutionDependencies

        # Protocol members are accessible via __protocol_attrs__ or annotations
        hints = ExecutionDependencies.__protocol_attrs__
        assert "agent_adapter" in hints
        assert "agent_registry" in hints

    # -- context_reducer --

    def test_context_reducer_defaults_to_none(self) -> None:
        """DefaultDependencies().context_reducer is None by default."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies()
        assert deps.context_reducer is None

    def test_context_reducer_stores_and_returns_instance(self) -> None:
        """DefaultDependencies(context_reducer=obj) stores and returns it."""
        from unittest.mock import AsyncMock

        from beddel.domain.models import DefaultDependencies

        mock_reducer = AsyncMock()
        mock_reducer.reduce = AsyncMock(return_value=[])
        deps = DefaultDependencies(context_reducer=mock_reducer)
        assert deps.context_reducer is mock_reducer

    def test_context_reducer_explicit_none(self) -> None:
        """Passing context_reducer=None explicitly is same as default."""
        from beddel.domain.models import DefaultDependencies

        deps = DefaultDependencies(context_reducer=None)
        assert deps.context_reducer is None

    def test_context_reducer_does_not_affect_other_properties(self) -> None:
        """Setting context_reducer leaves other deps at their defaults."""
        from unittest.mock import AsyncMock

        from beddel.domain.models import DefaultDependencies

        mock_reducer = AsyncMock()
        deps = DefaultDependencies(context_reducer=mock_reducer)
        assert deps.llm_provider is None
        assert deps.lifecycle_hooks is None
        assert deps.tracer is None
        assert deps.agent_adapter is None

    def test_execution_dependencies_protocol_has_context_reducer(self) -> None:
        """ExecutionDependencies Protocol defines context_reducer."""
        from beddel.domain.ports import ExecutionDependencies

        hints = ExecutionDependencies.__protocol_attrs__
        assert "context_reducer" in hints


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
        assert EventType.REFLECTION_START == "reflection_start"
        assert EventType.REFLECTION_END == "reflection_end"

    def test_member_count(self) -> None:
        assert len(EventType) == 11


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
            "AgentResult",
            "BeddelEvent",
            "DefaultDependencies",
            "EventType",
            "ExecutionContext",
            "ExecutionStrategy",
            "InterruptibleContext",
            "RetryConfig",
            "SKIPPED",
            "Step",
            "StrategyType",
            "ToolDeclaration",
            "Workflow",
        }
        assert set(models.__all__) == expected
