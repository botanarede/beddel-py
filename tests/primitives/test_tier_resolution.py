"""Tests for tier resolution in LLM/Chat primitives (AC 7, 8)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from beddel.adapters.tier_router import StaticTierRouter
from beddel.domain.models import DefaultDependencies, ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.primitives._llm_utils import build_kwargs, get_model
from beddel.primitives.chat import ChatPrimitive
from beddel.primitives.llm import LLMPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    *,
    llm_provider: Any = None,
    tier_router: Any = None,
) -> ExecutionContext:
    """Build an ExecutionContext with optional tier_router and provider."""
    deps = DefaultDependencies(
        llm_provider=llm_provider,
        tier_router=tier_router,
    )
    return ExecutionContext(
        workflow_id="wf-test",
        inputs={},
        step_results={},
        current_step_id="test-step",
        metadata={},
        deps=deps,
    )


def _make_provider(
    complete_return: dict[str, Any] | None = None,
) -> ILLMProvider:
    """Build a mock ILLMProvider."""
    provider: ILLMProvider = MagicMock(spec=ILLMProvider)
    provider.complete = AsyncMock(  # type: ignore[assignment]
        return_value=complete_return or {"content": "Hello!"},
    )
    return provider


# ---------------------------------------------------------------------------
# get_model() unit tests
# ---------------------------------------------------------------------------


class TestGetModelWithTierRouter:
    """Tier name resolves to concrete model via StaticTierRouter (AC 7)."""

    def test_fast_resolves_to_gpt4o_mini(self) -> None:
        # Arrange
        tier_router = StaticTierRouter()
        ctx = _make_context(tier_router=tier_router)
        config = {"model": "fast"}

        # Act
        result = get_model(config, ctx, "llm")

        # Assert
        assert result == "gpt-4o-mini"


class TestGetModelWithoutTierRouter:
    """Concrete model passes through unchanged when no tier_router (AC 7)."""

    def test_concrete_model_unchanged(self) -> None:
        # Arrange
        ctx = _make_context(tier_router=None)
        config = {"model": "gpt-4o"}

        # Act
        result = get_model(config, ctx, "llm")

        # Assert
        assert result == "gpt-4o"


class TestGetModelConcreteModelWithTierRouter:
    """Concrete model passes through when tier_router present but model is not a tier (AC 7)."""

    def test_concrete_model_falls_through(self) -> None:
        # Arrange
        tier_router = StaticTierRouter()
        ctx = _make_context(tier_router=tier_router)
        config = {"model": "gpt-4o"}

        # Act
        result = get_model(config, ctx, "llm")

        # Assert
        assert result == "gpt-4o"


# ---------------------------------------------------------------------------
# build_kwargs() unit tests
# ---------------------------------------------------------------------------


class TestBuildKwargsEffort:
    """Verify effort key is passed through in kwargs (AC 7)."""

    def test_effort_included(self) -> None:
        # Arrange
        config: dict[str, Any] = {"effort": "high"}

        # Act
        result = build_kwargs(config)

        # Assert
        assert result["effort"] == "high"


class TestBuildKwargsNoEffort:
    """Verify effort key is absent when not in config (AC 7)."""

    def test_effort_not_included(self) -> None:
        # Arrange
        config: dict[str, Any] = {"model": "gpt-4o"}

        # Act
        result = build_kwargs(config)

        # Assert
        assert "effort" not in result


# ---------------------------------------------------------------------------
# Integration tests — LLMPrimitive + ChatPrimitive with tier resolution
# ---------------------------------------------------------------------------


class TestLLMPrimitiveTierResolution:
    """LLMPrimitive resolves tier name to concrete model (AC 7)."""

    async def test_provider_called_with_resolved_model(self) -> None:
        # Arrange
        provider = _make_provider()
        tier_router = StaticTierRouter()
        ctx = _make_context(llm_provider=provider, tier_router=tier_router)
        config = {"model": "fast", "prompt": "Hello"}

        # Act
        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        # Assert — provider.complete called with resolved "gpt-4o-mini"
        provider.complete.assert_awaited_once_with(  # type: ignore[attr-defined]
            "gpt-4o-mini",
            [{"role": "user", "content": "Hello"}],
        )


class TestChatPrimitiveTierResolution:
    """ChatPrimitive resolves tier name to concrete model (AC 7)."""

    async def test_provider_called_with_resolved_model(self) -> None:
        # Arrange
        provider = _make_provider()
        tier_router = StaticTierRouter()
        ctx = _make_context(llm_provider=provider, tier_router=tier_router)
        config = {
            "model": "balanced",
            "messages": [
                {"role": "user", "content": "Hi"},
            ],
        }

        # Act
        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        # Assert — provider.complete called with resolved "gpt-4o"
        provider.complete.assert_awaited_once_with(  # type: ignore[attr-defined]
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
        )
