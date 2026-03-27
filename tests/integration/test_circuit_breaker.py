"""Integration tests for circuit breaker with WorkflowExecutor.

Tests the full lifecycle of the circuit breaker through the executor,
including state transitions, retry interaction, and backward compatibility.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from beddel.adapters.circuit_breaker import InMemoryCircuitBreaker
from beddel.domain.errors import AdapterError, ExecutionError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    CircuitBreakerConfig,
    DefaultDependencies,
    ExecutionContext,
    ExecutionStrategy,
    RetryConfig,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FailingLLMPrimitive(IPrimitive):
    """Primitive that raises AdapterError to simulate provider failures."""

    def __init__(self) -> None:
        self.call_count = 0

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        self.call_count += 1
        raise AdapterError("BEDDEL-ADAPT-002", "Provider unavailable")


class _SucceedingLLMPrimitive(IPrimitive):
    """Primitive that returns a successful result."""

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        return {"content": "Hello from LLM", "usage": {}}


def _make_llm_step(step_id: str = "llm-step", model: str = "openai/gpt-4o") -> Step:
    """Create an LLM step with the given model."""
    return Step(id=step_id, primitive="llm", config={"model": model, "prompt": "test"})


def _make_workflow(steps: list[Step]) -> Workflow:
    """Create a minimal workflow with the given steps."""
    return Workflow(id="test", name="test", steps=steps)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerFullLifecycle:
    """Test CLOSED → OPEN → HALF_OPEN → CLOSED lifecycle through the executor."""

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_circuit_breaker_full_lifecycle(
        self,
        mock_sleep: AsyncMock,
        mock_uniform: Any,
    ) -> None:
        """Full lifecycle: failures open circuit, recovery window allows probe, success closes."""
        cb = InMemoryCircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2, recovery_window=0.1, success_threshold=1)
        )

        failing_prim = _FailingLLMPrimitive()
        registry = PrimitiveRegistry()
        registry.register("llm", failing_prim)

        deps = DefaultDependencies(circuit_breaker=cb)
        executor = WorkflowExecutor(registry, deps=deps)
        workflow = _make_workflow([_make_llm_step()])

        # --- Phase 1: Two failures open the circuit ---
        # First failure (circuit stays closed)
        with pytest.raises(ExecutionError):
            await executor.execute(workflow, inputs={})
        assert cb.state("openai") == "closed"

        # Second failure (circuit opens)
        with pytest.raises(ExecutionError):
            await executor.execute(workflow, inputs={})
        assert cb.state("openai") == "open"

        # --- Phase 2: Circuit is open — requests blocked with CB-500 ---
        with pytest.raises(ExecutionError, match="BEDDEL-CB-500"):
            await executor.execute(workflow, inputs={})
        # Primitive should NOT have been called for the blocked request
        assert failing_prim.call_count == 2

        # --- Phase 3: Wait for recovery window → half-open ---
        time.sleep(0.15)
        assert cb.is_open("openai") is False  # triggers transition to half-open
        assert cb.state("openai") == "half-open"

        # --- Phase 4: Successful probe closes the circuit ---
        registry_ok = PrimitiveRegistry()
        registry_ok.register("llm", _SucceedingLLMPrimitive())
        executor_ok = WorkflowExecutor(registry_ok, deps=deps)

        result = await executor_ok.execute(workflow, inputs={})
        assert result["step_results"]["llm-step"] == {
            "content": "Hello from LLM",
            "usage": {},
        }
        assert cb.state("openai") == "closed"


class TestCircuitBreakerWithRetryStrategy:
    """Test that circuit breaker interacts correctly with retry strategy."""

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_circuit_breaker_with_retry_strategy(
        self,
        mock_sleep: AsyncMock,
        mock_uniform: Any,
    ) -> None:
        """Circuit breaker records the initial failure; retries bypass CB recording.

        The executor records failure in execute_step_with_context's except
        block.  Retry attempts inside _retry_step call _run_with_timeout
        directly, so their failures are NOT recorded by the circuit breaker.
        After retries exhaust, the single recorded failure leaves the circuit
        below threshold.  A second workflow execution records the 2nd failure,
        opening the circuit.  The 3rd execution gets CB-500 without hitting
        the provider.
        """
        cb = InMemoryCircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2, recovery_window=60.0, success_threshold=1)
        )

        failing_prim = _FailingLLMPrimitive()
        registry = PrimitiveRegistry()
        registry.register("llm", failing_prim)

        deps = DefaultDependencies(circuit_breaker=cb)
        executor = WorkflowExecutor(registry, deps=deps)

        step = Step(
            id="retry-step",
            primitive="llm",
            config={"model": "openai/gpt-4o", "prompt": "test"},
            execution_strategy=ExecutionStrategy(
                type=StrategyType.RETRY,
                retry=RetryConfig(max_attempts=3),
            ),
        )
        workflow = _make_workflow([step])

        # 1st execution: initial attempt fails → CB records 1 failure.
        # Retries exhaust (3 more attempts) but those don't record to CB.
        with pytest.raises(ExecutionError):
            await executor.execute(workflow, inputs={})
        assert cb.state("openai") == "closed"  # only 1 failure recorded
        assert failing_prim.call_count == 4  # initial + 3 retries

        # 2nd execution: initial attempt fails → CB records 2nd failure → circuit opens.
        with pytest.raises(ExecutionError):
            await executor.execute(workflow, inputs={})
        assert cb.state("openai") == "open"

        # 3rd execution: circuit is open → CB-500 raised immediately,
        # provider never called.
        call_count_before = failing_prim.call_count
        with pytest.raises(ExecutionError, match="BEDDEL-CB-500"):
            await executor.execute(workflow, inputs={})
        assert failing_prim.call_count == call_count_before  # no new provider calls


class TestBackwardCompatibilityNoCircuitBreaker:
    """Test that workflows without circuit breaker behave identically to pre-4.3."""

    async def test_backward_compatibility_no_circuit_breaker(self) -> None:
        """Full workflow execution without circuit breaker — identical to pre-4.3 baseline."""
        registry = PrimitiveRegistry()
        registry.register("llm", _SucceedingLLMPrimitive())

        # No circuit breaker in deps (default None)
        executor = WorkflowExecutor(registry)
        workflow = _make_workflow(
            [
                _make_llm_step("step-1"),
                _make_llm_step("step-2", model="anthropic/claude-3"),
            ]
        )

        result = await executor.execute(workflow, inputs={})

        # Both steps executed successfully
        assert result["step_results"]["step-1"] == {
            "content": "Hello from LLM",
            "usage": {},
        }
        assert result["step_results"]["step-2"] == {
            "content": "Hello from LLM",
            "usage": {},
        }
        # No errors, workflow completed normally
        assert "step_results" in result
        assert "metadata" in result
