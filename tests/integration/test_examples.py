"""Validation tests for example workflows in ``examples/workflows/``.

Ensures every shipped example parses correctly through the full
WorkflowParser pipeline (YAML → schema → variable-reference validation).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies
from beddel.domain.parser import WorkflowParser
from beddel.domain.ports import ILLMProvider
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).resolve().parents[4] / "examples" / "workflows"


def _load_example(filename: str) -> str:
    """Load an example workflow YAML from disk."""
    return (EXAMPLES_DIR / filename).read_text()


# ---------------------------------------------------------------------------
# hello.yaml
# ---------------------------------------------------------------------------


class TestHelloWorkflow:
    """Verify that examples/workflows/hello.yaml parses and validates."""

    def test_hello_parses_successfully(self) -> None:
        """hello.yaml loads and passes all parser validation phases."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        assert workflow.id == "hello-world"
        assert workflow.name == "Hello World"

    def test_hello_has_single_step(self) -> None:
        """hello.yaml contains exactly one step."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        assert len(workflow.steps) == 1

    def test_hello_step_uses_llm_primitive(self) -> None:
        """The step uses the 'llm' primitive with correct config keys."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        step = workflow.steps[0]
        assert step.id == "greet"
        assert step.primitive == "llm"
        assert "model" in step.config
        assert "prompt" in step.config

    def test_hello_uses_stable_model_name(self) -> None:
        """Model name is gemini/gemini-2.0-flash (no -exp suffix)."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        model = workflow.steps[0].config["model"]
        assert model == "gemini/gemini-2.0-flash"

    def test_hello_prompt_references_input_topic(self) -> None:
        """Prompt contains $input.topic for variable resolution."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        prompt = workflow.steps[0].config["prompt"]
        assert "$input.topic" in prompt


# ---------------------------------------------------------------------------
# Mock LLM provider for execution tests
# ---------------------------------------------------------------------------

MOCK_RESPONSE_CONTENT = "Hello! Here is a fun fact about your topic."


class MockLLMProvider(ILLMProvider):
    """Mock LLM provider that returns a fixed response without API calls."""

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "content": MOCK_RESPONSE_CONTENT,
            "model": model,
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            "finish_reason": "stop",
        }

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        yield "Hello!"


# ---------------------------------------------------------------------------
# hello.yaml — end-to-end execution
# ---------------------------------------------------------------------------


class TestHelloWorkflowExecution:
    """Verify that hello.yaml executes end-to-end with a mock LLM provider."""

    @pytest.mark.asyncio
    async def test_hello_executes_with_mock_provider(self) -> None:
        """Workflow runs to completion and returns the mock LLM response."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        registry = PrimitiveRegistry()
        register_builtins(registry)
        mock_provider = MockLLMProvider()
        executor = WorkflowExecutor(registry, deps=DefaultDependencies(llm_provider=mock_provider))

        result = await executor.execute(workflow, inputs={"topic": "astronomy"})

        assert "step_results" in result
        assert "greet" in result["step_results"]
        assert result["step_results"]["greet"]["content"] == MOCK_RESPONSE_CONTENT

    @pytest.mark.asyncio
    async def test_hello_execution_result_structure(self) -> None:
        """Result dict contains step_results and metadata with expected keys."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        registry = PrimitiveRegistry()
        register_builtins(registry)
        executor = WorkflowExecutor(
            registry, deps=DefaultDependencies(llm_provider=MockLLMProvider())
        )

        result = await executor.execute(workflow, inputs={"topic": "astronomy"})

        assert "step_results" in result
        assert "metadata" in result

        greet_result = result["step_results"]["greet"]
        assert "content" in greet_result
        assert "model" in greet_result
        assert "usage" in greet_result
        assert "finish_reason" in greet_result

    @pytest.mark.asyncio
    async def test_hello_resolves_input_variable(self) -> None:
        """Execution succeeds with a different topic, confirming variable resolution."""
        yaml_str = _load_example("hello.yaml")
        workflow = WorkflowParser.parse(yaml_str)

        registry = PrimitiveRegistry()
        register_builtins(registry)
        executor = WorkflowExecutor(
            registry, deps=DefaultDependencies(llm_provider=MockLLMProvider())
        )

        result = await executor.execute(workflow, inputs={"topic": "quantum physics"})

        assert "step_results" in result
        assert result["step_results"]["greet"]["content"] == MOCK_RESPONSE_CONTENT
