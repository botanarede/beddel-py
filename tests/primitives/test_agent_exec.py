"""Unit tests for beddel.primitives.agent_exec module."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from _helpers import make_context

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult, DefaultDependencies
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.agent_exec import AgentExecPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAgentAdapter:
    """Minimal IAgentAdapter-conforming adapter that captures call args."""

    def __init__(self, agent_id: str = "fake") -> None:
        self._agent_id = agent_id
        self.last_call: dict[str, Any] = {}

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        self.last_call = {
            "prompt": prompt,
            "model": model,
            "sandbox": sandbox,
            "tools": tools,
            "output_schema": output_schema,
        }
        return AgentResult(
            exit_code=0,
            output=prompt,
            events=[],
            files_changed=["file.py"],
            usage={"tokens": 100},
            agent_id=self._agent_id,
        )

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"type": "done"}


# ---------------------------------------------------------------------------
# Tests: Missing adapter config key (BEDDEL-AGENT-704)
# ---------------------------------------------------------------------------


class TestMissingAdapterConfig:
    async def test_raises_agent_704_when_adapter_key_missing(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": _FakeAgentAdapter("codex")})

        with pytest.raises(AgentError, match="BEDDEL-AGENT-704") as exc_info:
            await AgentExecPrimitive().execute({"prompt": "do stuff"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-704"

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec", step_id="my-step")
        ctx.deps = DefaultDependencies(agent_registry={"codex": _FakeAgentAdapter("codex")})

        with pytest.raises(AgentError) as exc_info:
            await AgentExecPrimitive().execute({"prompt": "do stuff"}, ctx)

        assert exc_info.value.details["primitive"] == "agent-exec"
        assert exc_info.value.details["step_id"] == "my-step"


# ---------------------------------------------------------------------------
# Tests: Missing prompt config key (BEDDEL-AGENT-705)
# ---------------------------------------------------------------------------


class TestMissingPromptConfig:
    async def test_raises_agent_705_when_prompt_key_missing(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": _FakeAgentAdapter("codex")})

        with pytest.raises(AgentError, match="BEDDEL-AGENT-705") as exc_info:
            await AgentExecPrimitive().execute({"adapter": "codex"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-705"

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec", step_id="prompt-step")
        ctx.deps = DefaultDependencies(agent_registry={"codex": _FakeAgentAdapter("codex")})

        with pytest.raises(AgentError) as exc_info:
            await AgentExecPrimitive().execute({"adapter": "codex"}, ctx)

        assert exc_info.value.details["primitive"] == "agent-exec"
        assert exc_info.value.details["step_id"] == "prompt-step"


# ---------------------------------------------------------------------------
# Tests: Registry not configured (BEDDEL-AGENT-700)
# ---------------------------------------------------------------------------


class TestRegistryNotConfigured:
    async def test_raises_agent_700_when_agent_registry_none(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry=None)

        with pytest.raises(AgentError, match="BEDDEL-AGENT-700") as exc_info:
            await AgentExecPrimitive().execute({"adapter": "codex", "prompt": "do stuff"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-700"

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec", step_id="reg-step")
        ctx.deps = DefaultDependencies(agent_registry=None)

        with pytest.raises(AgentError) as exc_info:
            await AgentExecPrimitive().execute({"adapter": "codex", "prompt": "do stuff"}, ctx)

        assert exc_info.value.details["primitive"] == "agent-exec"
        assert exc_info.value.details["step_id"] == "reg-step"


# ---------------------------------------------------------------------------
# Tests: Adapter not found in registry (BEDDEL-AGENT-706)
# ---------------------------------------------------------------------------


class TestAdapterNotFound:
    async def test_raises_agent_706_when_adapter_not_in_registry(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": _FakeAgentAdapter("codex")})

        with pytest.raises(AgentError, match="BEDDEL-AGENT-706") as exc_info:
            await AgentExecPrimitive().execute({"adapter": "missing", "prompt": "do stuff"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-706"

    async def test_error_details_contain_available_adapters(self) -> None:
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(
            agent_registry={
                "codex": _FakeAgentAdapter("codex"),
                "claude": _FakeAgentAdapter("claude"),
            }
        )

        with pytest.raises(AgentError) as exc_info:
            await AgentExecPrimitive().execute({"adapter": "missing", "prompt": "do stuff"}, ctx)

        details = exc_info.value.details
        assert details["adapter"] == "missing"
        assert sorted(details["available_adapters"]) == ["claude", "codex"]
        assert details["primitive"] == "agent-exec"


# ---------------------------------------------------------------------------
# Tests: Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_adapter_called_with_correct_prompt(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute({"adapter": "codex", "prompt": "review code"}, ctx)

        assert adapter.last_call["prompt"] == "review code"

    async def test_result_dict_has_expected_keys(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        result = await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "review code"}, ctx
        )

        assert set(result.keys()) == {"output", "files_changed", "usage"}

    async def test_result_values_match_adapter_output(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        result = await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "review code"}, ctx
        )

        assert result["output"] == "review code"
        assert result["files_changed"] == ["file.py"]
        assert result["usage"] == {"tokens": 100}


# ---------------------------------------------------------------------------
# Tests: Variable resolution
# ---------------------------------------------------------------------------


class TestVariableResolution:
    async def test_input_variable_resolved_in_prompt(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec", inputs={"code": "print('hello')"})
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute({"adapter": "codex", "prompt": "$input.code"}, ctx)

        assert adapter.last_call["prompt"] == "print('hello')"

    async def test_embedded_variable_resolved_in_prompt(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec", inputs={"lang": "Python"})
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "Review this $input.lang code"}, ctx
        )

        assert adapter.last_call["prompt"] == "Review this Python code"


# ---------------------------------------------------------------------------
# Tests: Optional config fields passed through to adapter
# ---------------------------------------------------------------------------


class TestOptionalConfigFields:
    async def test_model_passed_to_adapter(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "go", "model": "o3-mini"}, ctx
        )

        assert adapter.last_call["model"] == "o3-mini"

    async def test_sandbox_passed_to_adapter(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "go", "sandbox": "workspace-write"},
            ctx,
        )

        assert adapter.last_call["sandbox"] == "workspace-write"

    async def test_tools_passed_to_adapter(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "go", "tools": ["lint", "test"]},
            ctx,
        )

        assert adapter.last_call["tools"] == ["lint", "test"]

    async def test_output_schema_passed_to_adapter(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})
        schema = {"type": "object", "properties": {"score": {"type": "number"}}}

        await AgentExecPrimitive().execute(
            {"adapter": "codex", "prompt": "go", "output_schema": schema},
            ctx,
        )

        assert adapter.last_call["output_schema"] == schema


# ---------------------------------------------------------------------------
# Tests: Default sandbox
# ---------------------------------------------------------------------------


class TestDefaultSandbox:
    async def test_sandbox_defaults_to_read_only(self) -> None:
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        await AgentExecPrimitive().execute({"adapter": "codex", "prompt": "go"}, ctx)

        assert adapter.last_call["sandbox"] == "read-only"


# ---------------------------------------------------------------------------
# Tests: Execution failure wrapping
# ---------------------------------------------------------------------------


class TestExecutionFailure:
    async def test_non_agent_error_wrapped_as_701(self) -> None:
        class _FailingAdapter(_FakeAgentAdapter):
            async def execute(self, prompt: str, **kwargs: Any) -> AgentResult:
                raise ValueError("boom")

        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"bad": _FailingAdapter("bad")})

        with pytest.raises(AgentError, match="BEDDEL-AGENT-701") as exc_info:
            await AgentExecPrimitive().execute({"adapter": "bad", "prompt": "go"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-701"
        assert exc_info.value.details["original_error"] == "boom"
        assert exc_info.value.details["error_type"] == "ValueError"

    async def test_agent_error_passthrough_not_wrapped(self) -> None:
        class _AgentErrAdapter(_FakeAgentAdapter):
            async def execute(self, prompt: str, **kwargs: Any) -> AgentResult:
                raise AgentError(
                    code="BEDDEL-AGENT-999",
                    message="inner agent error",
                )

        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"err": _AgentErrAdapter("err")})

        with pytest.raises(AgentError) as exc_info:
            await AgentExecPrimitive().execute({"adapter": "err", "prompt": "go"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-999"


# ---------------------------------------------------------------------------
# Tests: Empty string edge cases (adapter and prompt)
# ---------------------------------------------------------------------------


class TestEmptyAdapterName:
    async def test_empty_adapter_name_raises_706_not_found(self) -> None:
        """Empty string adapter passes key check but fails registry lookup."""
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": _FakeAgentAdapter("codex")})

        with pytest.raises(AgentError, match="BEDDEL-AGENT-706") as exc_info:
            await AgentExecPrimitive().execute({"adapter": "", "prompt": "do stuff"}, ctx)

        assert exc_info.value.code == "BEDDEL-AGENT-706"
        assert exc_info.value.details["adapter"] == ""


class TestEmptyPrompt:
    async def test_empty_prompt_passed_to_adapter(self) -> None:
        """Empty string prompt passes key check and is sent to adapter."""
        adapter = _FakeAgentAdapter("codex")
        ctx = make_context(workflow_id="wf-agent-exec")
        ctx.deps = DefaultDependencies(agent_registry={"codex": adapter})

        result = await AgentExecPrimitive().execute({"adapter": "codex", "prompt": ""}, ctx)

        assert adapter.last_call["prompt"] == ""
        assert "output" in result


# ---------------------------------------------------------------------------
# Tests: register_builtins includes "agent-exec"
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    def test_registers_agent_exec_primitive(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert registry.get("agent-exec") is not None

    def test_registered_is_agent_exec_primitive_instance(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert isinstance(registry.get("agent-exec"), AgentExecPrimitive)
