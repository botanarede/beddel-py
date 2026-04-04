"""Unit tests for beddel.primitives.decide module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from _helpers import make_context

from beddel.adapters.decision_store import InMemoryDecisionStore
from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.errors import PrimitiveError
from beddel.domain.models import Decision, DefaultDependencies
from beddel.domain.ports import ILifecycleHook
from beddel.primitives.decide import DecidePrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_config(**overrides: Any) -> dict[str, Any]:
    """Return a valid decide config, with optional overrides."""
    base: dict[str, Any] = {
        "intent": "Select model",
        "options": ["gpt-4o", "claude-3-opus"],
        "chosen": "claude-3-opus",
        "reasoning": "Best quality for long documents",
    }
    base.update(overrides)
    return base


def _make_decide_context(
    *,
    workflow_id: str = "wf-decide",
    step_id: str | None = "step-decide",
    hooks: Any | None = None,
    decision_store: Any | None = None,
) -> Any:
    """Build an ExecutionContext with optional hooks and decision_store."""
    ctx = make_context(workflow_id=workflow_id, step_id=step_id)
    ctx.deps = DefaultDependencies(
        lifecycle_hooks=hooks,
        decision_store=decision_store,
    )
    return ctx


# ---------------------------------------------------------------------------
# Tests: Basic decision capture
# ---------------------------------------------------------------------------


class TestBasicDecisionCapture:
    async def test_returns_dict_with_all_decision_fields(self) -> None:
        ctx = _make_decide_context()
        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert isinstance(result, dict)
        assert result["intent"] == "Select model"
        assert result["options"] == ["gpt-4o", "claude-3-opus"]
        assert result["chosen"] == "claude-3-opus"
        assert result["reasoning"] == "Best quality for long documents"
        assert result["step_id"] == "step-decide"
        assert result["workflow_id"] == "wf-decide"
        assert result["id"]  # non-empty UUID string
        assert result["timestamp"]  # non-empty ISO timestamp

    async def test_options_defaults_to_empty_list(self) -> None:
        config = _valid_config()
        del config["options"]
        ctx = _make_decide_context()

        result = await DecidePrimitive().execute(config, ctx)

        assert result["options"] == []

    async def test_outcome_defaults_to_none(self) -> None:
        ctx = _make_decide_context()
        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["outcome"] is None

    async def test_unique_ids_per_execution(self) -> None:
        ctx = _make_decide_context()
        prim = DecidePrimitive()

        r1 = await prim.execute(_valid_config(), ctx)
        r2 = await prim.execute(_valid_config(), ctx)

        assert r1["id"] != r2["id"]


# ---------------------------------------------------------------------------
# Tests: Hook firing
# ---------------------------------------------------------------------------


class _FakeHook(ILifecycleHook):
    """Minimal hook that records on_decision calls."""

    def __init__(self) -> None:
        self.decisions: list[Decision] = []

    async def on_decision(self, decision: Decision) -> None:
        self.decisions.append(decision)


class TestHookFiring:
    async def test_fires_on_decision_hook(self) -> None:
        hook = _FakeHook()
        mgr = LifecycleHookManager()
        await mgr.add_hook(hook)
        ctx = _make_decide_context(hooks=mgr)

        await DecidePrimitive().execute(_valid_config(), ctx)

        assert len(hook.decisions) == 1
        assert hook.decisions[0].intent == "Select model"
        assert hook.decisions[0].chosen == "claude-3-opus"

    async def test_hook_error_is_swallowed(self) -> None:
        """Hook failure should not prevent the primitive from returning."""
        failing_hooks = AsyncMock()
        failing_hooks.on_decision = AsyncMock(side_effect=RuntimeError("hook boom"))
        ctx = _make_decide_context(hooks=failing_hooks)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select model"

    async def test_no_hooks_configured(self) -> None:
        """When lifecycle_hooks is None, primitive still works."""
        ctx = _make_decide_context(hooks=None)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select model"


# ---------------------------------------------------------------------------
# Tests: Store persistence
# ---------------------------------------------------------------------------


class TestStorePersistence:
    async def test_persists_decision_to_store(self) -> None:
        store = InMemoryDecisionStore()
        ctx = _make_decide_context(decision_store=store)

        await DecidePrimitive().execute(_valid_config(), ctx)

        decisions = await store.query(workflow_id="wf-decide")
        assert len(decisions) == 1
        assert decisions[0].intent == "Select model"

    async def test_store_not_configured_is_graceful(self) -> None:
        """When decision_store is None, primitive still works."""
        ctx = _make_decide_context(decision_store=None)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select model"

    async def test_store_error_is_swallowed(self) -> None:
        """Store failure should not prevent the primitive from returning."""
        failing_store = AsyncMock()
        failing_store.append = AsyncMock(side_effect=RuntimeError("store boom"))
        ctx = _make_decide_context(decision_store=failing_store)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        assert result["intent"] == "Select model"


# ---------------------------------------------------------------------------
# Tests: Missing config keys (error)
# ---------------------------------------------------------------------------


class TestMissingConfigKeys:
    @pytest.mark.parametrize("missing_key", ["intent", "chosen", "reasoning"])
    async def test_raises_prim_error_for_missing_required_key(self, missing_key: str) -> None:
        config = _valid_config()
        del config[missing_key]
        ctx = _make_decide_context()

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-400") as exc_info:
            await DecidePrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-400"
        assert exc_info.value.details["missing_key"] == missing_key

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        config = _valid_config()
        del config["intent"]
        ctx = _make_decide_context(step_id="my-step")

        with pytest.raises(PrimitiveError) as exc_info:
            await DecidePrimitive().execute(config, ctx)

        assert exc_info.value.details["primitive"] == "decide"
        assert exc_info.value.details["step_id"] == "my-step"


# ---------------------------------------------------------------------------
# Tests: Full round-trip
# ---------------------------------------------------------------------------


class TestFullRoundTrip:
    async def test_full_round_trip_with_hooks_and_store(self) -> None:
        """End-to-end: hook fires, store persists, result returned."""
        hook = _FakeHook()
        mgr = LifecycleHookManager()
        await mgr.add_hook(hook)
        store = InMemoryDecisionStore()
        ctx = _make_decide_context(hooks=mgr, decision_store=store)

        result = await DecidePrimitive().execute(_valid_config(), ctx)

        # Result is a dict
        assert result["intent"] == "Select model"
        assert result["chosen"] == "claude-3-opus"
        assert result["workflow_id"] == "wf-decide"

        # Hook received the Decision
        assert len(hook.decisions) == 1
        assert hook.decisions[0].id == result["id"]

        # Store has the Decision
        stored = await store.query(workflow_id="wf-decide")
        assert len(stored) == 1
        assert stored[0].id == result["id"]
        assert stored[0].timestamp == result["timestamp"]
