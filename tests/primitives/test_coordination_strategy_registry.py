"""Unit tests for coordination strategy registry injection (Story K1.17).

Tests:
- DefaultDependencies accepts and exposes coordination_strategy_registry
- ExecutionDependencies protocol includes coordination_strategy_registry
- CallAgentPrimitive resolves kit strategies from registry
- CallAgentPrimitive falls back to builtin strategies
- CallAgentPrimitive raises with combined strategy list when not found
- CLI _build_adapter_registries collects ICoordinationStrategy instances
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import (
    CoordinationResult,
    CoordinationTask,
    DefaultDependencies,
    ExecutionContext,
)
from beddel.domain.ports import ExecutionDependencies
from beddel.primitives.call_agent import CallAgentPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockStrategy:
    """Mock coordination strategy satisfying ICoordinationStrategy protocol."""

    def __init__(self, output: str = "mock-result") -> None:
        self._output = output

    async def coordinate(
        self,
        agents: dict[str, Any],
        task: CoordinationTask,
        context: ExecutionContext,
    ) -> CoordinationResult:
        return CoordinationResult(
            output=self._output,
            agent_results={},
        )


def _make_context(
    *,
    agent_registry: dict[str, Any] | None = None,
    coordination_strategy_registry: dict[str, Any] | None = None,
    step_id: str = "step-1",
) -> ExecutionContext:
    return ExecutionContext(
        workflow_id="wf-test",
        current_step_id=step_id,
        deps=DefaultDependencies(
            agent_registry=agent_registry,
            coordination_strategy_registry=coordination_strategy_registry,
        ),
    )


# ---------------------------------------------------------------------------
# Task 4.1: DefaultDependencies accepts and exposes coordination_strategy_registry
# ---------------------------------------------------------------------------


class TestDefaultDependenciesRegistry:
    """DefaultDependencies coordination_strategy_registry property."""

    def test_none_by_default(self) -> None:
        """coordination_strategy_registry is None when not provided."""
        deps = DefaultDependencies()
        assert deps.coordination_strategy_registry is None

    def test_accepts_dict(self) -> None:
        """coordination_strategy_registry accepts a dict of strategies."""
        strategy = _MockStrategy()
        deps = DefaultDependencies(coordination_strategy_registry={"custom-strategy": strategy})
        assert deps.coordination_strategy_registry is not None
        assert "custom-strategy" in deps.coordination_strategy_registry
        assert deps.coordination_strategy_registry["custom-strategy"] is strategy

    def test_empty_dict(self) -> None:
        """coordination_strategy_registry accepts an empty dict."""
        deps = DefaultDependencies(coordination_strategy_registry={})
        assert deps.coordination_strategy_registry == {}


# ---------------------------------------------------------------------------
# Task 4.1 (continued): ExecutionDependencies protocol
# ---------------------------------------------------------------------------


class TestExecutionDependenciesProtocol:
    """ExecutionDependencies Protocol includes coordination_strategy_registry."""

    def test_protocol_has_coordination_strategy_registry(self) -> None:
        """ExecutionDependencies Protocol defines coordination_strategy_registry."""
        assert "coordination_strategy_registry" in dir(ExecutionDependencies)
        inspect.getattr_static(ExecutionDependencies, "coordination_strategy_registry")


# ---------------------------------------------------------------------------
# Task 4.3: CallAgentPrimitive resolves kit strategy from registry
# ---------------------------------------------------------------------------


class TestCallAgentRegistryResolution:
    """CallAgentPrimitive resolves strategies from kit registry."""

    @pytest.mark.asyncio
    async def test_resolves_kit_strategy(self) -> None:
        """Kit strategy is resolved from coordination_strategy_registry."""
        mock_agent = AsyncMock()
        mock_agent.execute = AsyncMock(
            return_value=MagicMock(
                exit_code=0, output="done", events=[], files_changed=[], usage={}, agent_id="a1"
            )
        )
        strategy = _MockStrategy(output="kit-strategy-result")
        ctx = _make_context(
            agent_registry={"agent-a": mock_agent},
            coordination_strategy_registry={"kimi-agent-swarm": strategy},
        )

        primitive = CallAgentPrimitive()
        config = {
            "coordination": {
                "strategy": "kimi-agent-swarm",
                "agents": ["agent-a"],
                "prompt": "test prompt",
            }
        }

        result = await primitive.execute(config, ctx)
        assert result["output"] == "kit-strategy-result"

    @pytest.mark.asyncio
    async def test_kit_strategy_takes_priority_over_builtin(self) -> None:
        """If a kit registers 'supervisor', it overrides the builtin."""
        mock_agent = AsyncMock()
        mock_agent.execute = AsyncMock(
            return_value=MagicMock(
                exit_code=0, output="done", events=[], files_changed=[], usage={}, agent_id="a1"
            )
        )
        kit_supervisor = _MockStrategy(output="kit-supervisor")
        ctx = _make_context(
            agent_registry={"agent-a": mock_agent},
            coordination_strategy_registry={"supervisor": kit_supervisor},
        )

        primitive = CallAgentPrimitive()
        config = {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["agent-a"],
                "prompt": "test",
            }
        }

        result = await primitive.execute(config, ctx)
        # Kit registry takes priority — returns kit strategy output
        assert result["output"] == "kit-supervisor"


# ---------------------------------------------------------------------------
# Task 4.4: CallAgentPrimitive falls back to builtin strategies
# ---------------------------------------------------------------------------


class TestCallAgentBuiltinFallback:
    """CallAgentPrimitive falls back to builtins when registry empty or None."""

    @pytest.mark.asyncio
    async def test_builtin_supervisor_works_without_registry(self) -> None:
        """Builtin 'supervisor' strategy resolves when no kit registry."""
        # Supervisor needs an agent that returns decomposition JSON
        decomposition = '{"assignments": [{"agent": "analyst", "task": "do work"}]}'
        mock_agent = AsyncMock()
        mock_agent.execute = AsyncMock(
            return_value=MagicMock(
                exit_code=0,
                output=decomposition,
                events=[],
                files_changed=[],
                usage={},
                agent_id="supervisor",
            )
        )
        ctx = _make_context(
            agent_registry={"analyst": mock_agent},
            coordination_strategy_registry=None,
        )

        primitive = CallAgentPrimitive()
        config = {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["analyst"],
                "prompt": "Analyze this",
            }
        }

        # Should not raise — supervisor is a builtin strategy
        result = await primitive.execute(config, ctx)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_builtin_handoff_works_with_empty_registry(self) -> None:
        """Builtin 'handoff' strategy resolves with empty kit registry."""
        # Handoff marker agent
        mock_agent = AsyncMock()
        mock_agent.execute = AsyncMock(
            return_value=MagicMock(
                exit_code=0,
                output="[HANDOFF:done] result",
                events=[],
                files_changed=[],
                usage={},
                agent_id="agent-a",
            )
        )
        ctx = _make_context(
            agent_registry={"agent-a": mock_agent},
            coordination_strategy_registry={},
        )

        primitive = CallAgentPrimitive()
        config = {
            "coordination": {
                "strategy": "handoff",
                "agents": ["agent-a"],
                "prompt": "Do something",
            }
        }

        result = await primitive.execute(config, ctx)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Task 4.5: CallAgentPrimitive raises with combined strategy list
# ---------------------------------------------------------------------------


class TestCallAgentStrategyNotFound:
    """CallAgentPrimitive raises with available strategies from both sources."""

    @pytest.mark.asyncio
    async def test_raises_with_combined_list(self) -> None:
        """Error message lists both builtin and kit strategies."""
        kit_strategy = _MockStrategy()
        ctx = _make_context(
            agent_registry={"agent-a": AsyncMock()},
            coordination_strategy_registry={"my-custom-swarm": kit_strategy},
        )

        primitive = CallAgentPrimitive()
        config = {
            "coordination": {
                "strategy": "nonexistent-strategy",
                "agents": ["agent-a"],
                "prompt": "test",
            }
        }

        with pytest.raises(PrimitiveError) as exc_info:
            await primitive.execute(config, ctx)

        error_msg = exc_info.value.message
        # Should list both builtins and kit strategies
        assert "nonexistent-strategy" in error_msg
        assert "supervisor" in error_msg
        assert "handoff" in error_msg
        assert "parallel-dispatch" in error_msg
        assert "my-custom-swarm" in error_msg

    @pytest.mark.asyncio
    async def test_raises_builtins_only_when_no_registry(self) -> None:
        """Error lists only builtins when no kit registry is set."""
        ctx = _make_context(
            agent_registry={"agent-a": AsyncMock()},
            coordination_strategy_registry=None,
        )

        primitive = CallAgentPrimitive()
        config = {
            "coordination": {
                "strategy": "bad-strategy",
                "agents": ["agent-a"],
                "prompt": "test",
            }
        }

        with pytest.raises(PrimitiveError) as exc_info:
            await primitive.execute(config, ctx)

        error_msg = exc_info.value.message
        assert "bad-strategy" in error_msg
        assert "supervisor" in error_msg
        assert "handoff" in error_msg
        assert "parallel-dispatch" in error_msg


# ---------------------------------------------------------------------------
# Task 4.2 & 4.6: CLI _build_adapter_registries with ICoordinationStrategy
# ---------------------------------------------------------------------------


class TestBuildAdapterRegistriesCoordination:
    """_build_adapter_registries collects ICoordinationStrategy instances."""

    def test_collects_coordination_strategy(self) -> None:
        """Coordination strategies are collected into the third return element."""
        from beddel.cli.commands import _build_adapter_registries

        mock_strategy = _MockStrategy()
        mock_manifest = MagicMock()
        mock_manifest.kit.name = "agent-kimi-kit"

        mock_discovery = MagicMock()
        mock_discovery.manifests = [mock_manifest]

        with patch("beddel.tools.kits.load_kit_adapters") as mock_load:
            mock_load.return_value = {
                ("ICoordinationStrategy", "kimi-agent-swarm"): mock_strategy,
                ("IAgentAdapter", "kimi-adapter"): MagicMock(),
            }
            agent_reg, llm_prov, coord_reg = _build_adapter_registries(mock_discovery)

        assert "kimi-agent-swarm" in coord_reg
        assert coord_reg["kimi-agent-swarm"] is mock_strategy
        assert "kimi-adapter" in agent_reg
        assert llm_prov is None

    def test_empty_when_no_kits_flag(self) -> None:
        """Returns empty registries when no_kits=True."""
        from beddel.cli.commands import _build_adapter_registries

        mock_discovery = MagicMock()
        agent_reg, llm_prov, coord_reg = _build_adapter_registries(mock_discovery, no_kits=True)
        assert agent_reg == {}
        assert llm_prov is None
        assert coord_reg == {}

    def test_graceful_degradation_on_import_error(self) -> None:
        """Kit with failing adapters is skipped gracefully."""
        from beddel.cli.commands import _build_adapter_registries

        mock_manifest = MagicMock()
        mock_manifest.kit.name = "broken-kit"

        mock_discovery = MagicMock()
        mock_discovery.manifests = [mock_manifest]

        with patch("beddel.tools.kits.load_kit_adapters") as mock_load:
            mock_load.side_effect = ImportError("missing dep")
            agent_reg, llm_prov, coord_reg = _build_adapter_registries(mock_discovery)

        assert agent_reg == {}
        assert llm_prov is None
        assert coord_reg == {}
