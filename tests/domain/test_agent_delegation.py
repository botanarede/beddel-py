"""Unit tests for AgentDelegationStrategy.

Covers protocol conformance, workflow-to-prompt translation, adapter
delegation, lifecycle hook integration, interruptible context, error
scenarios, and config merging.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from beddel.domain.errors import AgentError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    AgentResult,
    DefaultDependencies,
    ExecutionContext,
    Step,
    Workflow,
)
from beddel.domain.ports import IHookManager
from beddel.domain.registry import PrimitiveRegistry
from beddel.domain.strategies.agent_delegation import AgentDelegationStrategy
from beddel.error_codes import (
    AGENT_ADAPTER_NOT_FOUND,
    AGENT_APPROVAL_NOT_IMPLEMENTED,
    AGENT_DELEGATION_FAILED,
    AGENT_NOT_CONFIGURED,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_RESULT = AgentResult(
    exit_code=0,
    output="agent output",
    events=[],
    files_changed=["file.py"],
    usage={"tokens": 100},
    agent_id="mock",
)


class _MockAdapter:
    """Recording adapter that captures calls and returns configurable results."""

    def __init__(
        self,
        result: AgentResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result or _DEFAULT_AGENT_RESULT
        self._error = error

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Record the call and return the configured result or raise."""
        self.calls.append({"prompt": prompt, "model": model, "sandbox": sandbox})
        if self._error:
            raise self._error
        return self._result

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield a single done event."""
        yield {"type": "done"}


class _RecordingHookManager(IHookManager):
    """Hook manager that records lifecycle calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def on_step_start(self, step_id: str, primitive: str) -> None:
        """Record on_step_start invocation."""
        self.calls.append(("on_step_start", step_id, primitive))

    async def on_step_end(self, step_id: str, result: Any) -> None:
        """Record on_step_end invocation."""
        self.calls.append(("on_step_end", step_id))

    async def on_error(self, step_id: str, error: Exception) -> None:
        """Record on_error invocation."""
        self.calls.append(("on_error", step_id, str(error)))


def _make_workflow(
    *,
    name: str = "test-wf",
    steps: list[Step] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Workflow:
    """Create a minimal Workflow for testing."""
    return Workflow(
        id="wf-1",
        name=name,
        description="A test workflow",
        steps=steps or [Step(id="s1", primitive="llm", config={"model": "gpt-4o"})],
        metadata=metadata or {},
    )


def _make_context(
    *,
    agent_registry: dict[str, Any] | None = None,
    lifecycle_hooks: IHookManager | None = None,
    inputs: dict[str, Any] | None = None,
    suspended: bool = False,
) -> ExecutionContext:
    """Create a minimal ExecutionContext for testing."""
    ctx = ExecutionContext(
        workflow_id="wf-1",
        inputs=inputs or {},
        deps=DefaultDependencies(
            agent_registry=agent_registry,
            lifecycle_hooks=lifecycle_hooks,
        ),
    )
    ctx.suspended = suspended
    return ctx


async def _noop_step_runner(step: Step, context: ExecutionContext) -> Any:
    """No-op step runner satisfying the StepRunner type alias."""
    return None


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify AgentDelegationStrategy satisfies IExecutionStrategy structurally."""

    def test_has_execute_with_correct_signature(self) -> None:
        """AgentDelegationStrategy.execute accepts (workflow, context, step_runner)."""
        strategy = AgentDelegationStrategy()
        sig = inspect.signature(strategy.execute)
        params = list(sig.parameters.keys())

        assert "workflow" in params
        assert "context" in params
        assert "step_runner" in params
        assert inspect.iscoroutinefunction(strategy.execute)


class TestBuildPrompt:
    """Verify _build_prompt() translates workflow into a structured prompt."""

    def test_prompt_includes_workflow_name_steps_and_inputs(self) -> None:
        """Prompt contains workflow name, step names, primitives, and input variables."""
        # Arrange
        steps = [
            Step(id="step-a", primitive="llm", config={"model": "gpt-4o"}),
            Step(id="step-b", primitive="tool", config={"name": "bash"}),
        ]
        workflow = _make_workflow(name="my-workflow", steps=steps)
        context = _make_context(inputs={"repo": "beddel", "branch": "main"})
        strategy = AgentDelegationStrategy()

        # Act
        prompt = strategy._build_prompt(workflow, context)

        # Assert — workflow name
        assert "Workflow: my-workflow" in prompt
        # Assert — step ids and primitives
        assert "step-a [llm]" in prompt
        assert "step-b [tool]" in prompt
        # Assert — step config values
        assert "model: gpt-4o" in prompt
        assert "name: bash" in prompt
        # Assert — input variables
        assert "repo: beddel" in prompt
        assert "branch: main" in prompt


class TestHappyPath:
    """Verify successful delegation populates context and resolves adapter."""

    async def test_execute_populates_step_results(self) -> None:
        """execute() stores output, files_changed, and usage in step_results."""
        # Arrange
        adapter = _MockAdapter()
        context = _make_context(agent_registry={"codex": adapter})
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})
        workflow = _make_workflow()

        # Act
        await strategy.execute(workflow, context, _noop_step_runner)

        # Assert
        result = context.step_results["agent-delegation"]
        assert result["output"] == "agent output"
        assert result["files_changed"] == ["file.py"]
        assert result["usage"] == {"tokens": 100}
        assert len(adapter.calls) == 1

    async def test_adapter_resolved_from_registry_by_config_name(self) -> None:
        """Adapter name from config is used to look up the adapter in agent_registry."""
        # Arrange
        codex = _MockAdapter()
        claude = _MockAdapter()
        context = _make_context(agent_registry={"codex": codex, "claude": claude})
        strategy = AgentDelegationStrategy(config={"adapter": "claude"})

        # Act
        await strategy.execute(_make_workflow(), context, _noop_step_runner)

        # Assert — only claude was called
        assert len(claude.calls) == 1
        assert len(codex.calls) == 0


class TestLifecycleHooks:
    """Verify lifecycle hooks are fired during execution."""

    async def test_on_step_start_and_on_step_end_fired(self) -> None:
        """Successful execution fires on_step_start then on_step_end."""
        # Arrange
        hooks = _RecordingHookManager()
        adapter = _MockAdapter()
        context = _make_context(
            agent_registry={"codex": adapter},
            lifecycle_hooks=hooks,
        )
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})

        # Act
        await strategy.execute(_make_workflow(), context, _noop_step_runner)

        # Assert
        assert ("on_step_start", "agent-delegation", "agent-delegation") in hooks.calls
        assert ("on_step_end", "agent-delegation") in hooks.calls
        # on_step_start comes before on_step_end
        start_idx = hooks.calls.index(("on_step_start", "agent-delegation", "agent-delegation"))
        end_idx = hooks.calls.index(("on_step_end", "agent-delegation"))
        assert start_idx < end_idx

    async def test_on_error_fired_when_adapter_raises(self) -> None:
        """on_error is fired when the adapter raises a non-AgentError exception."""
        # Arrange
        hooks = _RecordingHookManager()
        adapter = _MockAdapter(error=RuntimeError("boom"))
        context = _make_context(
            agent_registry={"codex": adapter},
            lifecycle_hooks=hooks,
        )
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})

        # Act
        with pytest.raises(AgentError) as exc_info:
            await strategy.execute(_make_workflow(), context, _noop_step_runner)

        # Assert
        assert exc_info.value.code == AGENT_DELEGATION_FAILED
        assert any(c[0] == "on_error" for c in hooks.calls)


class TestInterruptibleContext:
    """Verify early return when context is suspended."""

    async def test_suspended_context_returns_early(self) -> None:
        """execute() returns without delegating when context.suspended is True."""
        # Arrange
        adapter = _MockAdapter()
        context = _make_context(
            agent_registry={"codex": adapter},
            suspended=True,
        )
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})

        # Act
        await strategy.execute(_make_workflow(), context, _noop_step_runner)

        # Assert — adapter was never called
        assert len(adapter.calls) == 0
        assert "agent-delegation" not in context.step_results


class TestErrorScenarios:
    """Verify error codes for misconfiguration and delegation failures."""

    async def test_agent_registry_none_raises_700(self) -> None:
        """AgentError BEDDEL-AGENT-700 when agent_registry is None."""
        # Arrange
        context = _make_context(agent_registry=None)
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})

        # Act / Assert
        with pytest.raises(AgentError) as exc_info:
            await strategy.execute(_make_workflow(), context, _noop_step_runner)
        assert exc_info.value.code == AGENT_NOT_CONFIGURED

    async def test_adapter_not_found_raises_706(self) -> None:
        """AgentError BEDDEL-AGENT-706 when adapter name not in registry."""
        # Arrange
        context = _make_context(agent_registry={"other": _MockAdapter()})
        strategy = AgentDelegationStrategy(config={"adapter": "missing"})

        # Act / Assert
        with pytest.raises(AgentError) as exc_info:
            await strategy.execute(_make_workflow(), context, _noop_step_runner)
        assert exc_info.value.code == AGENT_ADAPTER_NOT_FOUND

    async def test_delegation_failure_wraps_as_707(self) -> None:
        """AgentError BEDDEL-AGENT-707 wraps adapter exceptions."""
        # Arrange
        adapter = _MockAdapter(error=ValueError("network down"))
        context = _make_context(agent_registry={"codex": adapter})
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})

        # Act / Assert
        with pytest.raises(AgentError) as exc_info:
            await strategy.execute(_make_workflow(), context, _noop_step_runner)
        assert exc_info.value.code == AGENT_DELEGATION_FAILED
        assert "network down" in exc_info.value.message
        assert exc_info.value.details["step_id"] == "agent-delegation"

    async def test_manual_approval_raises_708(self) -> None:
        """AgentError BEDDEL-AGENT-708 for approval_policy='manual'."""
        # Arrange
        context = _make_context(agent_registry={"codex": _MockAdapter()})
        strategy = AgentDelegationStrategy(
            config={"adapter": "codex", "approval_policy": "manual"},
        )

        # Act / Assert
        with pytest.raises(AgentError) as exc_info:
            await strategy.execute(_make_workflow(), context, _noop_step_runner)
        assert exc_info.value.code == AGENT_APPROVAL_NOT_IMPLEMENTED

    async def test_supervised_approval_raises_708(self) -> None:
        """AgentError BEDDEL-AGENT-708 for approval_policy='supervised'."""
        # Arrange
        context = _make_context(agent_registry={"codex": _MockAdapter()})
        strategy = AgentDelegationStrategy(
            config={"adapter": "codex", "approval_policy": "supervised"},
        )

        # Act / Assert
        with pytest.raises(AgentError) as exc_info:
            await strategy.execute(_make_workflow(), context, _noop_step_runner)
        assert exc_info.value.code == AGENT_APPROVAL_NOT_IMPLEMENTED


class TestConfigMerging:
    """Verify constructor config is used when workflow metadata doesn't override."""

    async def test_constructor_config_used_as_base(self) -> None:
        """Constructor config provides adapter name when workflow metadata is empty."""
        # Arrange
        adapter = _MockAdapter()
        context = _make_context(agent_registry={"codex": adapter})
        strategy = AgentDelegationStrategy(
            config={"adapter": "codex", "model": "gpt-4o", "sandbox": "workspace-write"},
        )
        workflow = _make_workflow(metadata={})

        # Act
        await strategy.execute(workflow, context, _noop_step_runner)

        # Assert — adapter received the constructor config values
        call = adapter.calls[0]
        assert call["model"] == "gpt-4o"
        assert call["sandbox"] == "workspace-write"

    async def test_workflow_metadata_overrides_constructor(self) -> None:
        """Workflow metadata execution_strategy keys override constructor config."""
        # Arrange
        adapter = _MockAdapter()
        context = _make_context(agent_registry={"codex": adapter})
        strategy = AgentDelegationStrategy(
            config={"adapter": "codex", "model": "gpt-4o", "sandbox": "read-only"},
        )
        workflow = _make_workflow(
            metadata={
                "execution_strategy": {"model": "claude-3", "sandbox": "danger-full-access"},
            },
        )

        # Act
        await strategy.execute(workflow, context, _noop_step_runner)

        # Assert — workflow metadata values win
        call = adapter.calls[0]
        assert call["model"] == "claude-3"
        assert call["sandbox"] == "danger-full-access"


class TestWorkflowExecutorIntegration:
    """Verify AgentDelegationStrategy integrates with WorkflowExecutor."""

    async def test_strategy_injected_and_invoked_via_executor(self) -> None:
        """WorkflowExecutor.execute() delegates to AgentDelegationStrategy.

        The executor creates DefaultDependencies without agent_registry,
        so the strategy raises BEDDEL-AGENT-700.  This proves:
        1. AgentDelegationStrategy is accepted as execution_strategy (Protocol conformance)
        2. The executor actually calls strategy.execute() (the error propagates)
        """
        registry = PrimitiveRegistry()
        executor = WorkflowExecutor(registry=registry)
        strategy = AgentDelegationStrategy(config={"adapter": "codex"})
        workflow = _make_workflow(
            metadata={"execution_strategy": {"adapter": "codex"}},
        )

        with pytest.raises(AgentError) as exc_info:
            await executor.execute(
                workflow,
                inputs={"repo": "beddel"},
                execution_strategy=strategy,
            )

        assert exc_info.value.code == AGENT_NOT_CONFIGURED
