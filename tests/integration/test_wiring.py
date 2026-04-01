"""Integration tests for full execution path: executor → context → primitive → adapter.

Verifies that the LLM primitive correctly reads the LiteLLM adapter from
execution context deps and that results propagate back through the
entire chain — without any real API calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from beddel_provider_litellm.adapter import LiteLLMAdapter

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, ExecutionContext, Step, Workflow
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.llm import LLMPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL = "openai/gpt-4o"
_PROMPT = "Say hello"


def _make_completion_response(
    *,
    content: str = "Hello from integration!",
    model: str = _MODEL,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int = 15,
    finish_reason: str = "stop",
) -> MagicMock:
    """Build a mock litellm completion response."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    response.choices = [choice]
    response.model = model
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens
    response.usage = usage
    return response


def _make_stream_chunks(texts: list[str]) -> list[MagicMock]:
    """Build a list of mock streaming chunks."""
    chunks = []
    for text in texts:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        chunks.append(chunk)
    return chunks


async def _async_iter(items: list[Any]) -> Any:
    """Return an async iterator over *items*."""
    for item in items:
        yield item


def _make_context(adapter: LiteLLMAdapter, step_id: str = "step-1") -> ExecutionContext:
    """Build an ExecutionContext wired with the given adapter."""
    return ExecutionContext(
        workflow_id="integration-test",
        deps=DefaultDependencies(llm_provider=adapter),
        current_step_id=step_id,
    )


# ---------------------------------------------------------------------------
# Tests: Full completion path (subtask 3.2)
# ---------------------------------------------------------------------------


class TestFullCompletionPath:
    """Verify: LLMPrimitive → context → LiteLLMAdapter → litellm.acompletion."""

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_result_propagates_from_adapter_through_primitive(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """End-to-end: primitive returns the adapter's structured response."""
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        config = {"model": _MODEL, "prompt": _PROMPT}

        result = await primitive.execute(config, context)

        assert result["content"] == "Hello from integration!"
        assert result["model"] == _MODEL
        assert result["finish_reason"] == "stop"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_adapter_receives_correct_model_and_messages(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """Primitive forwards model and built messages to the adapter."""
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        config = {"model": _MODEL, "prompt": _PROMPT}

        await primitive.execute(config, context)

        mock_acompletion.assert_awaited_once()
        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == _MODEL
        assert call_kwargs["messages"] == [{"role": "user", "content": _PROMPT}]

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_optional_kwargs_flow_through_entire_chain(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """temperature and max_tokens flow: config → primitive → adapter → litellm."""
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        config = {
            "model": _MODEL,
            "prompt": _PROMPT,
            "temperature": 0.7,
            "max_tokens": 256,
        }

        await primitive.execute(config, context)

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 256

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_messages_config_forwarded_directly(self, mock_acompletion: AsyncMock) -> None:
        """When config uses 'messages' instead of 'prompt', they pass through."""
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        config = {"model": _MODEL, "messages": messages}

        await primitive.execute(config, context)

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["messages"] == messages


# ---------------------------------------------------------------------------
# Tests: Full streaming path (subtask 3.3)
# ---------------------------------------------------------------------------


class TestFullStreamingPath:
    """Verify: LLMPrimitive (stream=True) → context → LiteLLMAdapter.stream → litellm."""

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_stream_chunks_propagate_through_primitive(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """Chunks from litellm flow back through adapter.stream → primitive result."""
        chunks = _make_stream_chunks(["He", "llo", " world", "!"])
        mock_acompletion.return_value = _async_iter(chunks)
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        config = {"model": _MODEL, "prompt": _PROMPT, "stream": True}

        result = await primitive.execute(config, context)

        assert "stream" in result
        collected: list[str] = []
        async for text in result["stream"]:
            collected.append(text)
        assert collected == ["He", "llo", " world", "!"]

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_stream_calls_acompletion_with_stream_flag(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """adapter.stream() passes stream=True to litellm.acompletion."""
        mock_acompletion.return_value = _async_iter([])
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        config = {"model": _MODEL, "prompt": _PROMPT, "stream": True}

        result = await primitive.execute(config, context)
        # Exhaust the generator to trigger the litellm call
        async for _ in result["stream"]:
            pass

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["model"] == _MODEL

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_stream_skips_none_content_chunks(self, mock_acompletion: AsyncMock) -> None:
        """None-content chunks are filtered out by the adapter during streaming."""
        chunk_ok = MagicMock()
        chunk_ok.choices = [MagicMock()]
        chunk_ok.choices[0].delta.content = "Hello"

        chunk_none = MagicMock()
        chunk_none.choices = [MagicMock()]
        chunk_none.choices[0].delta.content = None

        mock_acompletion.return_value = _async_iter([chunk_none, chunk_ok, chunk_none])
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        primitive = LLMPrimitive()
        config = {"model": _MODEL, "prompt": _PROMPT, "stream": True}

        result = await primitive.execute(config, context)
        collected: list[str] = []
        async for text in result["stream"]:
            collected.append(text)

        assert collected == ["Hello"]


# ---------------------------------------------------------------------------
# Tests: register_builtins wiring
# ---------------------------------------------------------------------------


class TestRegisterBuiltinsWiring:
    """Verify register_builtins() populates the registry and the registered
    primitive works end-to-end with a real adapter (mocked litellm)."""

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_registry_llm_primitive_completes_full_path(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """register_builtins → registry.get('llm') → execute → adapter → litellm."""
        mock_acompletion.return_value = _make_completion_response(content="registry works!")
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert registry.has("llm")
        primitive = registry.get("llm")

        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        config = {"model": _MODEL, "prompt": _PROMPT}

        result = await primitive.execute(config, context)

        assert result["content"] == "registry works!"
        mock_acompletion.assert_awaited_once()

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_registry_llm_primitive_streams_full_path(
        self, mock_acompletion: AsyncMock
    ) -> None:
        """register_builtins → registry.get('llm') → execute(stream) → adapter → litellm."""
        chunks = _make_stream_chunks(["stream", " via", " registry"])
        mock_acompletion.return_value = _async_iter(chunks)
        registry = PrimitiveRegistry()
        register_builtins(registry)

        primitive = registry.get("llm")
        adapter = LiteLLMAdapter()
        context = _make_context(adapter)
        config = {"model": _MODEL, "prompt": _PROMPT, "stream": True}

        result = await primitive.execute(config, context)
        collected: list[str] = []
        async for text in result["stream"]:
            collected.append(text)

        assert collected == ["stream", " via", " registry"]


# ---------------------------------------------------------------------------
# Tests: Caller-provided deps wiring (Story 4.0, Task 4)
# ---------------------------------------------------------------------------


class TestCallerProvidedDepsWiring:
    """Verify that WorkflowExecutor correctly propagates all caller-provided
    dependencies through to the execution context — mirroring the CLI ``run``
    command wiring pattern from Architecture section 9.1."""

    @patch("beddel_provider_litellm.adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_cli_wiring_round_trip(self, mock_acompletion: AsyncMock) -> None:
        """Full round-trip: build deps like CLI run, execute workflow, verify
        all caller-provided deps are accessible in context."""
        mock_acompletion.return_value = _make_completion_response()

        # --- Arrange: mirror CLI run() wiring ---
        registry = PrimitiveRegistry()
        register_builtins(registry)

        captured: list[ExecutionContext] = []

        class _CapturePrimitive(IPrimitive):
            async def execute(
                self, config: dict[str, Any], context: ExecutionContext
            ) -> dict[str, str]:
                captured.append(context)
                return {"status": "captured"}

        registry.register("_capture", _CapturePrimitive())

        adapter = LiteLLMAdapter()
        mock_agent_registry: dict[str, Any] = {"kiro-cli": MagicMock()}
        mock_workflow_loader = MagicMock()

        deps = DefaultDependencies(
            llm_provider=adapter,
            agent_registry=mock_agent_registry,
            tool_registry={},
            workflow_loader=mock_workflow_loader,
            registry=registry,
        )

        workflow = Workflow(
            id="wiring-test",
            name="Wiring Integration Test",
            steps=[
                Step(id="capture-step", primitive="_capture", config={}),
            ],
        )

        executor = WorkflowExecutor(registry, deps=deps)

        # --- Act ---
        await executor.execute(workflow)

        # --- Assert: all caller-provided deps present in context ---
        assert len(captured) == 1
        ctx = captured[0]
        assert ctx.deps.agent_registry is mock_agent_registry
        assert ctx.deps.tool_registry == {}
        assert ctx.deps.tool_registry is not None
        assert ctx.deps.workflow_loader is mock_workflow_loader
        assert ctx.deps.registry is registry
        assert ctx.deps.llm_provider is adapter
