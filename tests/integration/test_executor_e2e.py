"""End-to-end integration tests for WorkflowExecutor using spec fixtures.

Loads YAML workflow definitions from ``spec/fixtures/valid/`` and expected
resolution data from ``spec/fixtures/expected/``, then executes them through
the full parser → resolver → executor pipeline with mock primitives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import BeddelEvent, EventType, ExecutionContext
from beddel.domain.parser import WorkflowParser
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parents[4] / "spec" / "fixtures"


def _load_yaml(relative_path: str) -> str:
    """Load a YAML fixture from disk."""
    return (FIXTURES_DIR / relative_path).read_text()


def _load_expected(relative_path: str) -> dict[str, Any]:
    """Load an expected-output JSON fixture from disk."""
    return json.loads((FIXTURES_DIR / relative_path).read_text())


# ---------------------------------------------------------------------------
# Mock primitive
# ---------------------------------------------------------------------------


class StepDispatchPrimitive(IPrimitive):
    """Mock primitive that returns pre-configured results keyed by step id.

    Looks up ``context.current_step_id`` in the provided mapping and returns
    the corresponding value.  Falls back to a default if the step id is not
    found.
    """

    def __init__(
        self,
        results: dict[str, Any],
        *,
        default: Any = None,
    ) -> None:
        self._results = results
        self._default = default

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Return the pre-configured result for the current step."""
        step_id = context.current_step_id
        return self._results.get(step_id, self._default)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_executor(step_results: dict[str, Any]) -> WorkflowExecutor:
    """Build a WorkflowExecutor with a single mock 'llm' primitive."""
    registry = PrimitiveRegistry()
    registry.register("llm", StepDispatchPrimitive(step_results))
    return WorkflowExecutor(registry, hooks=LifecycleHookManager())


# ---------------------------------------------------------------------------
# 7.2 — Branching fixture: condition evaluation + retry strategy
# ---------------------------------------------------------------------------


class TestBranchingFixtureE2E:
    """Parse branching.yaml, execute with mock LLM, verify branching and retry."""

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_branching_takes_then_path_when_condition_truthy(
        self,
        mock_sleep: AsyncMock,
        mock_uniform: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Classify returns 'technical' → condition is truthy → then branch runs."""
        expected = _load_expected("expected/branching.expected.json")
        monkeypatch.setenv("TRANSLATE_API_KEY", expected["sample_env"]["TRANSLATE_API_KEY"])

        yaml_str = _load_yaml("valid/branching.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "classify": expected["sample_step_results"]["classify"],
            "technical_answer": {"answer": "TCP is a transport-layer protocol..."},
            "general_answer": {"answer": "TCP helps computers talk to each other."},
            "translate": {"translated": "Le TCP est un protocole..."},
        }
        executor = _build_executor(step_results)

        result = await executor.execute(
            workflow,
            inputs=expected["sample_inputs"],
        )

        sr = result["step_results"]

        # classify step executed and returned the mock result
        assert sr["classify"] == {"category": "technical"}

        # Condition "$stepResult.classify.category == 'technical'" resolves to
        # a non-empty string → truthy → then_steps execute
        assert "technical_answer" in sr
        assert sr["technical_answer"] == {"answer": "TCP is a transport-layer protocol..."}

        # general_answer is in the else branch — should NOT appear
        assert "general_answer" not in sr

        # translate step (skip strategy) should have executed successfully
        assert "translate" in sr

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_branching_retry_strategy_present_on_classify(
        self,
        mock_sleep: AsyncMock,
        mock_uniform: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Classify step has retry strategy — verify it succeeds on first call (no retries)."""
        expected = _load_expected("expected/branching.expected.json")
        monkeypatch.setenv("TRANSLATE_API_KEY", expected["sample_env"]["TRANSLATE_API_KEY"])

        yaml_str = _load_yaml("valid/branching.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "classify": expected["sample_step_results"]["classify"],
            "technical_answer": {"answer": "detailed answer"},
            "translate": {"translated": "traduit"},
        }
        executor = _build_executor(step_results)

        result = await executor.execute(workflow, inputs=expected["sample_inputs"])

        # No retries needed — sleep should not have been called
        mock_sleep.assert_not_called()
        assert result["step_results"]["classify"] == {"category": "technical"}

    @patch("beddel.domain.executor.random.uniform", return_value=1.0)
    @patch("beddel.domain.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_branching_skip_strategy_on_translate_failure(
        self,
        mock_sleep: AsyncMock,
        mock_uniform: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Translate step has skip strategy — failure should not abort workflow."""
        expected = _load_expected("expected/branching.expected.json")
        monkeypatch.setenv("TRANSLATE_API_KEY", expected["sample_env"]["TRANSLATE_API_KEY"])

        yaml_str = _load_yaml("valid/branching.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        call_count = 0

        class _FailOnTranslate(IPrimitive):
            """Succeeds for all steps except translate, which raises."""

            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                nonlocal call_count
                call_count += 1
                step_id = context.current_step_id
                if step_id == "translate":
                    raise RuntimeError("translation service unavailable")
                results_map: dict[str, Any] = {
                    "classify": expected["sample_step_results"]["classify"],
                    "technical_answer": {"answer": "detailed"},
                }
                return results_map.get(step_id)

        registry = PrimitiveRegistry()
        registry.register("llm", _FailOnTranslate())
        executor = WorkflowExecutor(registry)

        result = await executor.execute(workflow, inputs=expected["sample_inputs"])

        # translate failed but was skipped — stored as None
        assert result["step_results"]["translate"] is None
        # Other steps still succeeded
        assert result["step_results"]["classify"] == {"category": "technical"}


# ---------------------------------------------------------------------------
# 7.3 — Multi-step fixture: cross-step variable resolution
# ---------------------------------------------------------------------------


class TestMultiStepFixtureE2E:
    """Parse multi-step.yaml, execute with mock LLM, verify $stepResult.* resolution."""

    async def test_multi_step_variable_resolution_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Variables $input.*, $stepResult.*, $env.* resolve correctly across steps."""
        expected = _load_expected("expected/multi-step.expected.json")
        monkeypatch.setenv("REPORT_API_KEY", expected["sample_env"]["REPORT_API_KEY"])

        yaml_str = _load_yaml("valid/multi-step.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "summarize": expected["sample_step_results"]["summarize"],
            "extract_keywords": expected["sample_step_results"]["extract_keywords"],
            "report": {"report": "Final quantum computing report"},
        }
        executor = _build_executor(step_results)

        result = await executor.execute(
            workflow,
            inputs=expected["sample_inputs"],
        )

        sr = result["step_results"]

        # All three steps executed and stored results
        assert sr["summarize"] == {
            "text": "Quantum computing uses qubits to perform parallel computations.",
        }
        assert sr["extract_keywords"] == {
            "keywords": "qubits, superposition, entanglement",
        }
        assert sr["report"] == {"report": "Final quantum computing report"}

    async def test_multi_step_config_resolution_matches_expected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify the resolved config passed to each primitive matches expected JSON."""
        expected = _load_expected("expected/multi-step.expected.json")
        monkeypatch.setenv("REPORT_API_KEY", expected["sample_env"]["REPORT_API_KEY"])

        yaml_str = _load_yaml("valid/multi-step.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        # Capture the resolved configs passed to the primitive
        captured_configs: dict[str, dict[str, Any]] = {}

        class _CapturingPrimitive(IPrimitive):
            """Captures resolved config and returns step-specific results."""

            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                step_id = context.current_step_id
                assert step_id is not None
                captured_configs[step_id] = dict(config)
                results_map: dict[str, Any] = {
                    "summarize": expected["sample_step_results"]["summarize"],
                    "extract_keywords": expected["sample_step_results"]["extract_keywords"],
                    "report": {"report": "done"},
                }
                return results_map.get(step_id)

        registry = PrimitiveRegistry()
        registry.register("llm", _CapturingPrimitive())
        executor = WorkflowExecutor(registry)

        await executor.execute(workflow, inputs=expected["sample_inputs"])

        # Verify resolved configs match expected fixture data
        for step_id, step_expected in expected["steps"].items():
            assert step_id in captured_configs, f"Step '{step_id}' was not executed"
            for key, value in step_expected["config"].items():
                assert captured_configs[step_id][key] == value, (
                    f"Step '{step_id}' config['{key}']: "
                    f"expected {value!r}, got {captured_configs[step_id].get(key)!r}"
                )

    async def test_multi_step_sequential_execution_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Steps execute in order: summarize → extract_keywords → report."""
        expected = _load_expected("expected/multi-step.expected.json")
        monkeypatch.setenv("REPORT_API_KEY", expected["sample_env"]["REPORT_API_KEY"])

        yaml_str = _load_yaml("valid/multi-step.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        execution_order: list[str] = []

        class _OrderTrackingPrimitive(IPrimitive):
            """Tracks execution order and returns step-specific results."""

            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                step_id = context.current_step_id
                assert step_id is not None
                execution_order.append(step_id)
                results_map: dict[str, Any] = {
                    "summarize": expected["sample_step_results"]["summarize"],
                    "extract_keywords": expected["sample_step_results"]["extract_keywords"],
                    "report": {"report": "done"},
                }
                return results_map.get(step_id)

        registry = PrimitiveRegistry()
        registry.register("llm", _OrderTrackingPrimitive())
        executor = WorkflowExecutor(registry)

        await executor.execute(workflow, inputs=expected["sample_inputs"])

        assert execution_order == ["summarize", "extract_keywords", "report"]


# ---------------------------------------------------------------------------
# 7.4 — execute_stream() event sequence for multi-step workflow
# ---------------------------------------------------------------------------


class TestExecuteStreamE2E:
    """Verify execute_stream() emits correct event sequence for a multi-step workflow."""

    async def test_stream_event_sequence_multi_step(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Event types follow: WF_START, (STEP_START, STEP_END)×3, WF_END."""
        expected = _load_expected("expected/multi-step.expected.json")
        monkeypatch.setenv("REPORT_API_KEY", expected["sample_env"]["REPORT_API_KEY"])

        yaml_str = _load_yaml("valid/multi-step.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "summarize": expected["sample_step_results"]["summarize"],
            "extract_keywords": expected["sample_step_results"]["extract_keywords"],
            "report": {"report": "Final report"},
        }
        executor = _build_executor(step_results)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(
            workflow,
            inputs=expected["sample_inputs"],
        ):
            events.append(event)

        types = [e.event_type for e in events]
        assert types == [
            EventType.WORKFLOW_START,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.WORKFLOW_END,
        ]

    async def test_stream_events_carry_correct_step_ids(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each STEP_START/STEP_END event references the correct step id."""
        expected = _load_expected("expected/multi-step.expected.json")
        monkeypatch.setenv("REPORT_API_KEY", expected["sample_env"]["REPORT_API_KEY"])

        yaml_str = _load_yaml("valid/multi-step.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "summarize": expected["sample_step_results"]["summarize"],
            "extract_keywords": expected["sample_step_results"]["extract_keywords"],
            "report": {"report": "done"},
        }
        executor = _build_executor(step_results)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(
            workflow,
            inputs=expected["sample_inputs"],
        ):
            events.append(event)

        step_events = [e for e in events if e.step_id is not None]
        step_ids = [e.step_id for e in step_events]
        assert step_ids == [
            "summarize",
            "summarize",
            "extract_keywords",
            "extract_keywords",
            "report",
            "report",
        ]

    async def test_stream_workflow_start_carries_inputs(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """WORKFLOW_START event data includes workflow_id and inputs."""
        expected = _load_expected("expected/multi-step.expected.json")
        monkeypatch.setenv("REPORT_API_KEY", expected["sample_env"]["REPORT_API_KEY"])

        yaml_str = _load_yaml("valid/multi-step.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "summarize": expected["sample_step_results"]["summarize"],
            "extract_keywords": expected["sample_step_results"]["extract_keywords"],
            "report": {"report": "done"},
        }
        executor = _build_executor(step_results)

        events: list[BeddelEvent] = []
        async for event in executor.execute_stream(
            workflow,
            inputs=expected["sample_inputs"],
        ):
            events.append(event)

        ws_event = events[0]
        assert ws_event.event_type == EventType.WORKFLOW_START
        assert ws_event.data["workflow_id"] == "multi-step-workflow"
        assert ws_event.data["inputs"] == expected["sample_inputs"]


# ---------------------------------------------------------------------------
# Parallel execution strategy integration
# ---------------------------------------------------------------------------


class TestParallelStrategyIntegration:
    """Verify ParallelExecutionStrategy works with WorkflowExecutor.execute()."""

    async def test_parallel_strategy_integration(self) -> None:
        """Mixed sequential + parallel steps execute correctly via ParallelExecutionStrategy."""
        from beddel.domain.strategies.parallel import ParallelExecutionStrategy

        # Build a workflow with mixed sequential and parallel steps.
        # Steps: seq_start → (par_a ∥ par_b) → seq_end
        yaml_str = """\
id: parallel-integration-test
name: Parallel Integration Test
steps:
  - id: seq_start
    primitive: llm
    config:
      prompt: "start"
  - id: par_a
    primitive: llm
    parallel: true
    config:
      prompt: "parallel a"
  - id: par_b
    primitive: llm
    parallel: true
    config:
      prompt: "parallel b"
  - id: seq_end
    primitive: llm
    config:
      prompt: "end"
"""
        workflow = WorkflowParser.parse(yaml_str)

        step_results: dict[str, Any] = {
            "seq_start": {"out": "started"},
            "par_a": {"out": "a_done"},
            "par_b": {"out": "b_done"},
            "seq_end": {"out": "finished"},
        }
        executor = _build_executor(step_results)

        result = await executor.execute(
            workflow,
            inputs={"topic": "test"},
            execution_strategy=ParallelExecutionStrategy(),
        )

        sr = result["step_results"]

        # All four steps produced results
        assert sr["seq_start"] == {"out": "started"}
        assert sr["par_a"] == {"out": "a_done"}
        assert sr["par_b"] == {"out": "b_done"}
        assert sr["seq_end"] == {"out": "finished"}
