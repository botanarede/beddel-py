"""Integration tests for ``beddel serve`` wiring round-trip (AC 2, 4).

Verifies that the serve command's dependency wiring pattern — constructing
:class:`DefaultDependencies` with all caller-provided deps and passing them
to :func:`create_beddel_handler` — correctly propagates through to the
:class:`WorkflowExecutor` and ultimately to the execution context.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, ExecutionContext, Step, Workflow
from beddel.domain.ports import ILLMProvider, IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.integrations.fastapi import create_beddel_handler
from beddel.primitives import register_builtins

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(primitive_name: str = "mock") -> Workflow:
    """Create a minimal single-step workflow for testing."""
    return Workflow(
        id="serve-wiring-test",
        name="Serve Wiring Test",
        steps=[Step(id="step-1", primitive=primitive_name)],
    )


def _build_serve_deps(registry: PrimitiveRegistry) -> DefaultDependencies:
    """Build ``DefaultDependencies`` mirroring the ``beddel serve`` pattern.

    Constructs deps with all caller-provided fields matching the serve
    command: ``llm_provider``, ``agent_registry``, ``tool_registry``,
    ``workflow_loader``, and ``registry``.
    """
    mock_adapter = MagicMock(spec=ILLMProvider)
    mock_agent_registry: dict[str, Any] = {"kiro-cli": MagicMock()}
    mock_tool_registry: dict[str, Any] = {"my-tool": lambda: None}
    mock_workflow_loader = MagicMock()

    return DefaultDependencies(
        llm_provider=mock_adapter,
        agent_registry=mock_agent_registry,
        tool_registry=mock_tool_registry,
        workflow_loader=mock_workflow_loader,
        registry=registry,
    )


def _make_completion_response() -> MagicMock:
    """Build a mock litellm completion response."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = "mock"
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.model = "openai/gpt-4o"
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15
    response.usage = usage
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestServeWiringRoundTrip:
    """Verify that the ``beddel serve`` wiring pattern correctly propagates
    all caller-provided deps through ``create_beddel_handler`` to the
    ``WorkflowExecutor``."""

    def test_handler_forwards_deps_to_executor(self) -> None:
        """``create_beddel_handler`` passes ``deps`` to ``WorkflowExecutor``.

        Mirrors the serve command pattern: construct ``DefaultDependencies``
        with all caller-provided deps, then call ``create_beddel_handler``
        with ``deps=deps``.  Verifies the executor receives the deps and
        individual params (provider, hooks, tracer) are NOT passed.
        """
        # Arrange
        registry = PrimitiveRegistry()
        register_builtins(registry)
        deps = _build_serve_deps(registry)

        # Act
        with patch(
            "beddel.integrations.fastapi.WorkflowExecutor",
        ) as mock_executor_cls:
            create_beddel_handler(_make_workflow(), deps=deps)

        # Assert
        mock_executor_cls.assert_called_once()
        call_kwargs = mock_executor_cls.call_args
        assert call_kwargs.kwargs["deps"] is deps
        assert "provider" not in call_kwargs.kwargs
        assert "hooks" not in call_kwargs.kwargs
        assert "tracer" not in call_kwargs.kwargs

    def test_executor_deps_contain_agent_registry(self) -> None:
        """Executor's deps expose ``agent_registry`` from serve wiring."""
        registry = PrimitiveRegistry()
        register_builtins(registry)
        deps = _build_serve_deps(registry)

        with patch(
            "beddel.integrations.fastapi.WorkflowExecutor",
        ) as mock_executor_cls:
            create_beddel_handler(_make_workflow(), deps=deps)

        forwarded_deps = mock_executor_cls.call_args.kwargs["deps"]
        assert forwarded_deps.agent_registry is not None
        assert "kiro-cli" in forwarded_deps.agent_registry

    def test_executor_deps_contain_tool_registry(self) -> None:
        """Executor's deps expose ``tool_registry`` matching --tool flag."""
        registry = PrimitiveRegistry()
        register_builtins(registry)
        deps = _build_serve_deps(registry)

        with patch(
            "beddel.integrations.fastapi.WorkflowExecutor",
        ) as mock_executor_cls:
            create_beddel_handler(_make_workflow(), deps=deps)

        forwarded_deps = mock_executor_cls.call_args.kwargs["deps"]
        assert forwarded_deps.tool_registry is not None
        assert "my-tool" in forwarded_deps.tool_registry

    def test_executor_deps_contain_workflow_loader(self) -> None:
        """Executor's deps expose ``workflow_loader`` from serve wiring."""
        registry = PrimitiveRegistry()
        register_builtins(registry)
        deps = _build_serve_deps(registry)

        with patch(
            "beddel.integrations.fastapi.WorkflowExecutor",
        ) as mock_executor_cls:
            create_beddel_handler(_make_workflow(), deps=deps)

        forwarded_deps = mock_executor_cls.call_args.kwargs["deps"]
        assert forwarded_deps.workflow_loader is not None

    @patch(
        "beddel.adapters.litellm_adapter.litellm.acompletion",
        new_callable=AsyncMock,
    )
    async def test_serve_wiring_full_round_trip(
        self,
        mock_acompletion: AsyncMock,
    ) -> None:
        """Full round-trip: build deps like serve, execute via handler's
        executor, verify all caller-provided deps in execution context.

        Uses a ``_CapturePrimitive`` to intercept the execution context
        and assert that every dep from the serve wiring pattern is
        accessible at runtime.
        """
        mock_acompletion.return_value = _make_completion_response()

        # Arrange — mirror serve command wiring
        registry = PrimitiveRegistry()
        register_builtins(registry)

        captured: list[ExecutionContext] = []

        class _CapturePrimitive(IPrimitive):
            """Primitive that captures the execution context."""

            async def execute(
                self,
                config: dict[str, Any],
                context: ExecutionContext,
            ) -> dict[str, str]:
                """Capture context and return a status dict."""
                captured.append(context)
                return {"status": "captured"}

        registry.register("_capture", _CapturePrimitive())

        mock_adapter = MagicMock(spec=ILLMProvider)
        mock_agent_registry: dict[str, Any] = {"kiro-cli": MagicMock()}
        mock_tool_registry: dict[str, Any] = {"my-tool": lambda: None}
        mock_workflow_loader = MagicMock()

        deps = DefaultDependencies(
            llm_provider=mock_adapter,
            agent_registry=mock_agent_registry,
            tool_registry=mock_tool_registry,
            workflow_loader=mock_workflow_loader,
            registry=registry,
        )

        workflow = Workflow(
            id="serve-round-trip",
            name="Serve Round-Trip Test",
            steps=[Step(id="capture-step", primitive="_capture", config={})],
        )

        # Act — construct executor the same way create_beddel_handler does
        executor = WorkflowExecutor(registry, deps=deps)
        await executor.execute(workflow)

        # Assert — all caller-provided deps accessible in context
        assert len(captured) == 1
        ctx = captured[0]
        assert ctx.deps.agent_registry is mock_agent_registry
        assert ctx.deps.tool_registry is mock_tool_registry
        assert ctx.deps.workflow_loader is mock_workflow_loader
        assert ctx.deps.registry is registry
        assert ctx.deps.llm_provider is mock_adapter
