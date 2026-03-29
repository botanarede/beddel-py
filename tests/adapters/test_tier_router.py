"""Tests for StaticTierRouter adapter."""

from __future__ import annotations

import pytest

from beddel.adapters.tier_router import StaticTierRouter
from beddel.domain.errors import PrimitiveError
from beddel.error_codes import TIER_UNKNOWN


class TestStaticTierRouter:
    """Verify default tier mapping resolves correctly (AC 7)."""

    def test_route_fast_returns_gpt4o_mini(self) -> None:
        # Arrange
        router = StaticTierRouter()

        # Act
        result = router.route("fast")

        # Assert
        assert result == "gpt-4o-mini"

    def test_route_balanced_returns_gpt4o(self) -> None:
        router = StaticTierRouter()

        result = router.route("balanced")

        assert result == "gpt-4o"

    def test_route_powerful_returns_claude_opus(self) -> None:
        router = StaticTierRouter()

        result = router.route("powerful")

        assert result == "claude-opus-4"


class TestStaticTierRouterCustomTiers:
    """Verify custom tier mapping overrides defaults (AC 7)."""

    def test_custom_tier_overrides_default(self) -> None:
        # Arrange
        router = StaticTierRouter(tiers={"fast": "llama-3"})

        # Act
        result = router.route("fast")

        # Assert
        assert result == "llama-3"

    def test_custom_tiers_do_not_include_defaults(self) -> None:
        """Custom tiers fully replace defaults — 'balanced' is not available."""
        router = StaticTierRouter(tiers={"fast": "llama-3"})

        with pytest.raises(PrimitiveError) as exc_info:
            router.route("balanced")

        assert exc_info.value.code == TIER_UNKNOWN


class TestStaticTierRouterUnknownTier:
    """Verify unknown tier raises PrimitiveError with BEDDEL-PRIM-320 (AC 7)."""

    def test_unknown_tier_raises_primitive_error(self) -> None:
        # Arrange
        router = StaticTierRouter()

        # Act & Assert
        with pytest.raises(PrimitiveError) as exc_info:
            router.route("unknown")

        assert exc_info.value.code == TIER_UNKNOWN
        assert exc_info.value.code == "BEDDEL-PRIM-320"
        assert "unknown" in exc_info.value.message.lower()


class TestStaticTierRouterPromptComplexity:
    """Verify prompt_complexity parameter is accepted without error (AC 7)."""

    def test_route_with_prompt_complexity(self) -> None:
        # Arrange
        router = StaticTierRouter()

        # Act — should not raise
        result = router.route("fast", prompt_complexity=0.5)

        # Assert
        assert result == "gpt-4o-mini"
