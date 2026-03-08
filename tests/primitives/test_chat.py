"""Unit tests for beddel.primitives.chat module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _helpers import make_context, make_provider

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.chat import ChatPrimitive

# ---------------------------------------------------------------------------
# Tests: Multi-turn conversation (subtask 3.2)
# ---------------------------------------------------------------------------


class TestMultiTurnConversation:
    """Tests for multi-turn message assembly: system + history + new user message."""

    async def test_system_and_messages_sent_to_provider(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "You are helpful",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "More"},
            ],
        }

        prim = ChatPrimitive()
        result = await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "More"},
            ],
        )
        assert result == {"content": "Hello!"}

    async def test_system_prepended_to_messages(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "Be concise",
            "messages": [{"role": "user", "content": "Hi"}],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert messages[0] == {"role": "system", "content": "Be concise"}

    async def test_messages_only_without_system(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        )

    async def test_empty_messages_defaults_to_empty_list(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o"}

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with("gpt-4o", [])

    async def test_temperature_and_max_tokens_forwarded(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.7,
            "max_tokens": 256,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
            temperature=0.7,
            max_tokens=256,
        )


# ---------------------------------------------------------------------------
# Tests: Context windowing by max_messages (subtask 3.3)
# ---------------------------------------------------------------------------


class TestContextWindowingByMaxMessages:
    """Tests for max_messages trimming: oldest non-system dropped, system preserved."""

    async def test_trims_oldest_non_system_when_over_limit(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {"role": "user", "content": "msg4"},
                {"role": "user", "content": "msg5"},
            ],
            "max_messages": 3,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 3
        assert messages == [
            {"role": "user", "content": "msg3"},
            {"role": "user", "content": "msg4"},
            {"role": "user", "content": "msg5"},
        ]

    async def test_system_messages_always_preserved(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "You are helpful",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {"role": "user", "content": "msg4"},
                {"role": "user", "content": "msg5"},
            ],
            "max_messages": 2,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # System message preserved + last 2 non-system
        assert messages[0] == {"role": "system", "content": "You are helpful"}
        assert len(messages) == 3
        assert messages[1] == {"role": "user", "content": "msg4"}
        assert messages[2] == {"role": "user", "content": "msg5"}

    async def test_no_trimming_when_under_limit(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
            ],
            "max_messages": 10,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 3

    async def test_default_max_messages_is_50(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        # 5 messages, well under default 50 — all should be kept
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": f"msg{i}"} for i in range(5)],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 5


# ---------------------------------------------------------------------------
# Tests: Context windowing by max_context_tokens (subtask 3.4)
# ---------------------------------------------------------------------------


class TestContextWindowingByMaxContextTokens:
    """Tests for token-based trimming of conversation history."""

    async def test_trims_oldest_when_over_token_budget(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        # Each "x" * 40 content => max(1, 10) + 4 = 14 tokens per message
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 40},  # 14 tokens
                {"role": "user", "content": "y" * 40},  # 14 tokens
                {"role": "user", "content": "z" * 40},  # 14 tokens
            ],
            "max_context_tokens": 28,  # budget for 2 messages only (2 × 14)
            "max_messages": None,  # disable count limit
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # Oldest message dropped, last 2 kept (28 tokens fits 2 × 14)
        assert len(messages) == 2
        assert messages[0]["content"] == "y" * 40
        assert messages[1]["content"] == "z" * 40

    async def test_system_tokens_deducted_from_budget(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        # System: "s" * 20 => max(1, 5) + 4 = 9 tokens
        # Each user msg: "u" * 40 => max(1, 10) + 4 = 14 tokens
        # Budget = 23, system costs 9, leaves 14 for non-system (1 message)
        config = {
            "model": "gpt-4o",
            "system": "s" * 20,
            "messages": [
                {"role": "user", "content": "u" * 40},  # 14 tokens
                {"role": "user", "content": "v" * 40},  # 14 tokens
            ],
            "max_context_tokens": 23,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # System preserved + only last user message fits
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "s" * 20}
        assert messages[1]["content"] == "v" * 40

    async def test_no_trimming_when_under_budget(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 40},
                {"role": "user", "content": "y" * 40},
            ],
            "max_context_tokens": 1000,  # plenty of budget
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 2

    async def test_zero_budget_drops_all_non_system_messages(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "Keep me",
            "messages": [
                {"role": "user", "content": "x" * 40},
                {"role": "user", "content": "y" * 40},
            ],
            "max_context_tokens": 0,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # Only system message survives — zero budget means no room for non-system
        assert len(messages) == 1
        assert messages[0] == {"role": "system", "content": "Keep me"}

    async def test_negative_budget_drops_all_non_system_messages(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        # System message alone exceeds budget
        config = {
            "model": "gpt-4o",
            "system": "s" * 100,  # 29 tokens, exceeds budget of 5
            "messages": [{"role": "user", "content": "hi"}],
            "max_context_tokens": 5,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # System preserved, all non-system dropped (negative remaining budget)
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    async def test_unlimited_when_max_context_tokens_none(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        # Default max_context_tokens is None — no token trimming
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 400},
                {"role": "user", "content": "y" * 400},
                {"role": "user", "content": "z" * 400},
            ],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 3

    async def test_short_messages_estimated_as_nonzero_tokens(self) -> None:
        """Short messages like 'ok' (2 chars) must count as >=1 token, not 0."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        # "ok" (2 chars) => max(1, 2 // 4) + 4 = max(1, 0) + 4 = 5 tokens each
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "ok"},  # 5 tokens
                {"role": "user", "content": "ok"},  # 5 tokens
                {"role": "user", "content": "ok"},  # 5 tokens
            ],
            "max_context_tokens": 10,  # budget for 2 messages only (2 x 5)
            "max_messages": None,  # disable count limit
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # Oldest message dropped — proves short messages are NOT zero-cost
        assert len(messages) == 2
        assert messages[0]["content"] == "ok"
        assert messages[1]["content"] == "ok"


# ---------------------------------------------------------------------------
# Tests: Tool-call pair preservation during token-budget trimming (Story 1.27)
# ---------------------------------------------------------------------------


class TestToolCallPairPreservation:
    """Tests that tool-call / tool-response pairs are dropped atomically.

    When token-budget trimming removes one side of a tool-call pair, the
    other side must also be removed to prevent invalid message sequences
    that LLM providers would reject.
    """

    async def test_dropping_tool_response_also_drops_assistant_tool_call(
        self,
    ) -> None:
        """AC 1: Dropping a tool response also drops the paired assistant."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # Token costs:
        #   user "x"*40          = 14 tokens
        #   assistant (content=None, tool_calls) = 5 tokens
        #   tool "result" (6 chars) = 5 tokens
        #   user "y"*40          = 14 tokens
        #   assistant "ok"       = 5 tokens
        # Total non-system = 14 + 5 + 5 + 14 + 5 = 43 tokens
        #
        # Budget = 19 → only the last user + last assistant fit (14 + 5).
        # FIFO pops user("x"*40) first (14 tokens, total→29, still > 19).
        # Next pop: assistant(tool_calls) — pair-aware logic also drops
        # the tool response, removing 5 + 5 = 10 tokens (total→19, fits).
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 40},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
                },
                {"role": "tool", "tool_call_id": "tc1", "content": "result"},
                {"role": "user", "content": "y" * 40},
                {"role": "assistant", "content": "ok"},
            ],
            "max_context_tokens": 19,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # Only the last user + last assistant survive.
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "y" * 40}
        assert messages[1] == {"role": "assistant", "content": "ok"}
        # Verify no tool messages leaked through.
        roles = [m["role"] for m in messages]
        assert "tool" not in roles

    async def test_dropping_assistant_tool_call_also_drops_tool_responses(
        self,
    ) -> None:
        """AC 2: Dropping an assistant tool_call drops all tool responses."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # Token costs:
        #   assistant (content=None, tool_calls) = 5 tokens
        #   tool "result" (6 chars) = 5 tokens
        #   user "y"*40          = 14 tokens
        # Total non-system = 5 + 5 + 14 = 24 tokens
        #
        # Budget = 14 → only the last user fits.
        # FIFO pops assistant(tool_calls) first — pair-aware logic also
        # drops the tool response (5 + 5 = 10 removed, total→14, fits).
        config = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
                },
                {"role": "tool", "tool_call_id": "tc1", "content": "result"},
                {"role": "user", "content": "y" * 40},
            ],
            "max_context_tokens": 14,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # Only the last user message survives.
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "y" * 40}

    async def test_multi_tool_call_pair_all_responses_dropped(self) -> None:
        """AC 2 + multi: Dropping assistant with multiple tool_calls drops all responses."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # Token costs:
        #   assistant (content=None, 2 tool_calls) = 5 tokens
        #   tool "result" tc1 (6 chars) = 5 tokens
        #   tool "result" tc2 (6 chars) = 5 tokens
        #   user "y"*40          = 14 tokens
        # Total non-system = 5 + 5 + 5 + 14 = 29 tokens
        #
        # Budget = 14 → only the last user fits.
        # FIFO pops assistant(tool_calls) first — pair-aware logic also
        # drops both tool responses (5 + 5 + 5 = 15 removed, total→14).
        config = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "tc1", "type": "function", "function": {"name": "f1"}},
                        {"id": "tc2", "type": "function", "function": {"name": "f2"}},
                    ],
                },
                {"role": "tool", "tool_call_id": "tc1", "content": "result"},
                {"role": "tool", "tool_call_id": "tc2", "content": "result"},
                {"role": "user", "content": "y" * 40},
            ],
            "max_context_tokens": 14,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # Only the last user message survives — both tool responses removed.
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "y" * 40}
        # Double-check no tool or tool_call messages leaked.
        for m in messages:
            assert m.get("role") != "tool"
            assert "tool_calls" not in m

    async def test_non_tool_messages_unaffected_by_pair_logic(self) -> None:
        """AC 5: Non-tool conversations behave identically to pre-change FIFO."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # Token costs (no tool_calls anywhere):
        #   user "x"*40          = 14 tokens
        #   assistant "ok"       = 5 tokens
        #   user "y"*40          = 14 tokens
        #   assistant "ok"       = 5 tokens
        # Total non-system = 14 + 5 + 14 + 5 = 38 tokens
        #
        # Budget = 19 → only the last user + last assistant fit (14 + 5).
        # FIFO pops user("x"*40) first (14 tokens, total→24, still > 19).
        # Next pop: assistant("ok") (5 tokens, total→19, fits).
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 40},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "y" * 40},
                {"role": "assistant", "content": "ok"},
            ],
            "max_context_tokens": 19,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # Oldest messages dropped via plain FIFO — pair logic is a no-op.
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "y" * 40}
        assert messages[1] == {"role": "assistant", "content": "ok"}
        # No tool artefacts should appear.
        for m in messages:
            assert m.get("role") != "tool"
            assert "tool_calls" not in m

    async def test_system_messages_never_dropped_with_tool_pairs(self) -> None:
        """AC 3: System messages survive even when tool-call pairs are dropped."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # Token costs:
        #   system "You are a bot" (13 chars) = 7 tokens  (always preserved)
        #   assistant (content=None, tool_calls) = 5 tokens
        #   tool "result" (6 chars) = 5 tokens
        #   user "y"*40          = 14 tokens
        # Non-system total = 5 + 5 + 14 = 24 tokens
        # System cost = 7 tokens → remaining budget = 14 - 7 = 7 tokens
        #
        # Budget = 14 → after reserving 7 for system, only 7 left.
        # FIFO pops assistant(tool_calls) — pair-aware logic also drops
        # the tool response (5 + 5 = 10 removed, non-system total→14).
        # Still over 7 remaining budget? 14 > 7, so user("y"*40) also
        # gets dropped.  Let's use a bigger budget so user survives.
        #
        # Revised budget = 21 → system 7 → remaining 14.
        # Non-system = 5 + 5 + 14 = 24 > 14.
        # FIFO pops assistant(tool_calls) + paired tool → 10 removed → 14.
        # 14 == 14, fits. User message survives.
        config = {
            "model": "gpt-4o",
            "system": "You are a bot",
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "f"}}],
                },
                {"role": "tool", "tool_call_id": "tc1", "content": "result"},
                {"role": "user", "content": "y" * 40},
            ],
            "max_context_tokens": 21,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # System message always preserved at position 0.
        assert messages[0] == {"role": "system", "content": "You are a bot"}
        # User message survives; tool pair was dropped.
        assert len(messages) == 2
        assert messages[1] == {"role": "user", "content": "y" * 40}
        # No tool artefacts leaked.
        roles = [m["role"] for m in messages]
        assert "tool" not in roles

    async def test_max_messages_trim_does_not_orphan_tool_response(
        self,
    ) -> None:
        """AC 1+4: max_messages slice that cuts between tool_call and tool response.

        When the max_messages slice boundary falls between an assistant
        tool_call and its tool response, the orphaned tool response at
        the start of the retained list must also be dropped.
        """
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # 5 non-system messages:
        #   [0] user "msg1"
        #   [1] user "msg2"
        #   [2] assistant (tool_calls=[tc1])
        #   [3] tool tc1 "result"
        #   [4] user "msg3"
        #
        # max_messages=2 → slice keeps last 2: [tool(tc1), user("msg3")]
        # tool at position 0 is orphaned (its assistant was sliced off).
        # The while-loop drops it → only [user("msg3")] remains.
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "tc1", "type": "function", "function": {"name": "f"}},
                    ],
                },
                {"role": "tool", "tool_call_id": "tc1", "content": "result"},
                {"role": "user", "content": "msg3"},
            ],
            "max_context_tokens": None,
            "max_messages": 2,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # Only the last user message survives — orphaned tool was dropped.
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "msg3"}
        # No tool artefacts leaked.
        roles = [m["role"] for m in messages]
        assert "tool" not in roles

    async def test_max_messages_trim_does_not_orphan_tool_call(
        self,
    ) -> None:
        """AC 2+4: max_messages slice drops assistant but retains its tool responses.

        When the assistant tool_call is dropped by the max_messages slice
        but its tool responses land at the start of the retained list,
        all orphaned tool responses must be cleaned up.
        """
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # 5 non-system messages:
        #   [0] user "msg1"
        #   [1] assistant (tool_calls=[tc1, tc2])
        #   [2] tool tc1 "r1"
        #   [3] tool tc2 "r2"
        #   [4] user "msg3"
        #
        # max_messages=3 → slice keeps last 3: [tool(tc1), tool(tc2), user("msg3")]
        # Both tool responses at positions 0-1 are orphaned (their assistant
        # was sliced off). The while-loop drops both → only [user("msg3")].
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "tc1", "type": "function", "function": {"name": "f1"}},
                        {"id": "tc2", "type": "function", "function": {"name": "f2"}},
                    ],
                },
                {"role": "tool", "tool_call_id": "tc1", "content": "r1"},
                {"role": "tool", "tool_call_id": "tc2", "content": "r2"},
                {"role": "user", "content": "msg3"},
            ],
            "max_context_tokens": None,
            "max_messages": 3,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        # Only the last user message survives — both orphaned tools dropped.
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "msg3"}
        # No tool or tool_call artefacts leaked.
        for m in messages:
            assert m.get("role") != "tool"
            assert "tool_calls" not in m

    async def test_max_messages_trim_drops_trailing_orphaned_assistant_tool_call(
        self,
    ) -> None:
        """CR-5 fix: max_messages slice keeps assistant(tool_calls) at end but
        its tool responses were sliced off — the orphaned assistant is dropped."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)

        # 4 non-system messages:
        #   [0] user "msg1"
        #   [1] user "msg2"
        #   [2] user "msg3"
        #   [3] assistant (tool_calls=[tc1])   <-- no tool response follows
        #
        # max_messages=2 → slice keeps last 2: [user("msg3"), assistant(tc1)]
        # assistant at end has tool_calls but no tool responses in the list.
        # Reverse orphan cleanup drops it → only [user("msg3")] remains.
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "tc1", "type": "function", "function": {"name": "f"}},
                    ],
                },
            ],
            "max_context_tokens": None,
            "max_messages": 2,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]

        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "msg3"}
        for m in messages:
            assert "tool_calls" not in m


# ---------------------------------------------------------------------------
# Tests: Streaming mode (subtask 3.5)
# ---------------------------------------------------------------------------


class TestStreamingMode:
    """Tests for streaming chat invocation returning async generator."""

    async def test_stream_returns_dict_with_stream_key(self) -> None:
        provider = make_provider(stream_chunks=["a", "b", "c"])
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream me"}],
            "stream": True,
        }

        prim = ChatPrimitive()
        result = await prim.execute(config, ctx)

        assert "stream" in result

    async def test_stream_yields_expected_chunks(self) -> None:
        chunks = ["He", "llo", " world"]
        provider = make_provider(stream_chunks=chunks)
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream me"}],
            "stream": True,
        }

        prim = ChatPrimitive()
        result = await prim.execute(config, ctx)

        collected: list[str] = []
        async for chunk in result["stream"]:
            collected.append(chunk)

        assert collected == chunks

    async def test_stream_calls_provider_stream_not_complete(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream"}],
            "stream": True,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.stream.assert_called_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Stream"}],
        )
        provider.complete.assert_not_awaited()

    async def test_stream_forwards_kwargs(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream"}],
            "stream": True,
            "temperature": 0.5,
            "max_tokens": 100,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.stream.assert_called_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Stream"}],
            temperature=0.5,
            max_tokens=100,
        )

    async def test_non_streaming_when_stream_false(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once()
        provider.stream.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Missing provider (subtask 3.6)
# ---------------------------------------------------------------------------


class TestMissingProvider:
    """Tests for BEDDEL-PRIM-003 when llm_provider is absent or invalid."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        ctx = make_context(llm_provider=None)
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"

    async def test_error_message_mentions_llm_provider(self) -> None:
        ctx = make_context(llm_provider=None)
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "llm_provider" in exc_info.value.message

    async def test_error_details_contain_step_id_and_primitive_type(self) -> None:
        ctx = make_context(llm_provider=None, step_id="my-step")
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "my-step",
            "primitive_type": "chat",
        }

    async def test_raises_for_invalid_provider_type(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-test", current_step_id="step-1")
        mock_deps = MagicMock()
        mock_deps.llm_provider = object()  # plain object, not ILLMProvider
        mock_deps.lifecycle_hooks = []
        ctx.deps = mock_deps
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"
        assert "ILLMProvider" in exc_info.value.message


# ---------------------------------------------------------------------------
# Tests: Missing model (subtask 3.7)
# ---------------------------------------------------------------------------


class TestMissingModel:
    """Tests for BEDDEL-PRIM-004 when model config key is absent."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"messages": [{"role": "user", "content": "Hi"}]}  # no model

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-004"

    async def test_error_message_mentions_model(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "model" in exc_info.value.message

    async def test_error_details_contain_missing_key(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider, step_id="s2")
        config = {"messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "s2",
            "primitive_type": "chat",
            "missing_key": "model",
        }


# ---------------------------------------------------------------------------
# Tests: register_builtins (subtask 3.8)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    """Tests for register_builtins() registering 'chat' in the registry."""

    def test_registers_chat_primitive(self) -> None:
        registry = PrimitiveRegistry()

        register_builtins(registry)

        assert registry.has("chat")

    def test_registered_chat_is_chat_primitive_instance(self) -> None:
        registry = PrimitiveRegistry()

        register_builtins(registry)

        assert isinstance(registry.get("chat"), ChatPrimitive)


# ---------------------------------------------------------------------------
# Tests: Message validation (Task 5 — AC 4)
# ---------------------------------------------------------------------------


class TestMessageValidation:
    """Tests that ChatPrimitive rejects malformed input messages."""

    async def test_chat_raises_on_message_missing_role(self) -> None:
        """ChatPrimitive raises PrimitiveError when a message lacks 'role'."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"content": "hi"}],  # missing role
        }

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-006"

    async def test_chat_raises_on_message_missing_content(self) -> None:
        """ChatPrimitive raises PrimitiveError when a message lacks 'content'."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user"}],  # missing content
        }

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-006"
