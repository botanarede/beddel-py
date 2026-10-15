"""Enforcement tests for MCP tool steps in the tool primitive (Story 1.2b, Task 2).

Covers AC 9 (allowlist at run time), AC 11 (schema validator seam) and
AC 13 (MCP error codes preserved, no raw exception text) with a fake client
that follows the kit construction contract.  No network, no SDK, no kit and
no credential are used.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _helpers import make_context
from _mcp_fakes import (
    FAKE_SECRET_MARKER,
    ClientScript,
    EventLog,
    FakeMCPClient,
    assert_marker_absent,
    assert_unchained,
    enable_log_capture,
    stub_validate_tool_arguments,
)

from beddel.domain.errors import BeddelError, ExecutionError, MCPError, ParseError, PrimitiveError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, ExecutionContext, Step, Workflow
from beddel.domain.registry import PrimitiveRegistry
from beddel.error_codes import (
    ALL_CODES,
    MCP_SCHEMA_VALIDATION_FAILED,
    PRIM_MISSING_TOOL_REGISTRY,
    PRIM_TOOL_EXEC_FAILED,
    PRIM_TOOL_NOT_ALLOWED,
    PRIM_TOOL_TIMEOUT,
)
from beddel.primitives import register_builtins
from beddel.primitives import tool as tool_module
from beddel.primitives.tool import ToolPrimitive

SERVER = "acme_srv"
TOOL = "do_thing"
QUALIFIED = f"{SERVER}:{TOOL}"
ENDPOINT = "https://fake.example/mcp"

NOT_ALLOWED_MESSAGE = "MCP tool is not admitted by the workflow allowed_tools list"
CALL_FAILED_MESSAGE = "MCP tool call failed"
DISCOVERY_FAILED_MESSAGE = "MCP tool schema discovery failed"


def _client(script: ClientScript | None = None) -> tuple[FakeMCPClient, EventLog]:
    log = EventLog()
    client = FakeMCPClient("mcp-streamable-http", ENDPOINT, "none", log=log, script=script)
    return client, log


def _context(
    client: FakeMCPClient,
    allowed: list[str] | None,
    *,
    inputs: dict[str, Any] | None = None,
) -> ExecutionContext:
    metadata: dict[str, Any] = {"_workflow_allowed_tools": allowed}
    return make_context(
        inputs=inputs,
        metadata=metadata,
        tool_registry={},
        mcp_registry={SERVER: client},
        step_id="step-mcp",
    )


def _config(**extra: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"tool": TOOL, "mcp_server": SERVER}
    config.update(extra)
    return config


def _mcp_codes() -> list[str]:
    return sorted(name for name in ALL_CODES if name.startswith("MCP_"))


# ---------------------------------------------------------------------------
# AC 9: allowlist at run time
# ---------------------------------------------------------------------------


class TestMCPRunTimeAllowlist:
    @pytest.mark.parametrize(
        "allowed",
        [
            None,
            [],
            [f"{SERVER}:other"],
            [TOOL],  # a bare tool name never admits an MCP tool
            [f"{SERVER}:*"],  # no wildcard
            [f"{SERVER.upper()}:{TOOL}"],  # no case folding
            [f"{SERVER}:{TOOL.upper()}"],
            [f" {QUALIFIED}"],  # no trimming
            [f"{QUALIFIED} "],
            [f"other_srv:{TOOL}"],
        ],
        ids=[
            "none",
            "empty",
            "other-tool",
            "bare-name",
            "wildcard",
            "server-case",
            "tool-case",
            "leading-space",
            "trailing-space",
            "other-server",
        ],
    )
    async def test_refused_before_any_client_use(
        self, allowed: list[str] | None, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        client, log = _client()
        ctx = _context(client, allowed)

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute(
                _config(
                    arguments={"text": FAKE_SECRET_MARKER},
                    validate_schema=True,
                ),
                ctx,
            )

        err = exc_info.value
        assert err.code == PRIM_TOOL_NOT_ALLOWED == "BEDDEL-PRIM-304"
        assert err.message == NOT_ALLOWED_MESSAGE
        # No lifecycle event at all: not connected, not listed, not called.
        assert log.names() == ["constructed"]
        for value in (SERVER, TOOL, QUALIFIED):
            assert value not in err.message
            assert value not in repr(err.details)
        assert "_tool_context" not in ctx.metadata
        assert "beddel._mcp_tool_schemas" not in ctx.metadata
        assert_marker_absent(err, caplog)

    async def test_refusal_does_not_resolve_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []

        class _SpyResolver:
            def __init__(self) -> None:
                calls.append("constructed")

            def resolve(self, value: Any, context: Any) -> Any:
                calls.append("resolve")
                return value

        monkeypatch.setattr(tool_module, "VariableResolver", _SpyResolver)
        client, _ = _client()
        ctx = _context(client, [f"{SERVER}:other"])

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute(_config(arguments={"text": "$input.x"}), ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-304"
        assert calls == []

    async def test_exact_qualified_name_is_admitted(self) -> None:
        client, log = _client(ClientScript(call_result="done"))
        ctx = _context(client, [QUALIFIED])

        result = await ToolPrimitive().execute(_config(arguments={"text": "hi"}), ctx)

        assert result["tool"] == TOOL
        assert result["mcp_server"] == SERVER
        assert result["result"] == "done"
        assert result["arguments"] == {"text": "hi"}
        assert isinstance(result["duration_ms"], int)
        assert log.names() == ["constructed", "connected", "call_tool"]
        assert ctx.metadata["_tool_context"] == {
            "tool_name": TOOL,
            "mcp_server": SERVER,
            "arguments": {"text": "hi"},
        }

    async def test_tool_name_with_colon_is_matched_whole(self) -> None:
        client, log = _client()
        ctx = _context(client, [f"{SERVER}:a:b"])

        await ToolPrimitive().execute({"tool": "a:b", "mcp_server": SERVER}, ctx)
        assert log.count("call_tool") == 1

        # The bare suffix of the local rule must not admit it.
        ctx_bare = _context(client, ["b", "a:b"])
        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "a:b", "mcp_server": SERVER}, ctx_bare)
        assert exc_info.value.code == "BEDDEL-PRIM-304"
        assert log.count("call_tool") == 1

    async def test_non_string_tool_is_refused(self) -> None:
        client, log = _client()
        ctx = _context(client, [f"{SERVER}:['x']", f"{SERVER}:{{'a': 1}}"])

        for bad_tool in (["x"], {"a": 1}, 7, None):
            with pytest.raises(PrimitiveError) as exc_info:
                await ToolPrimitive().execute({"tool": bad_tool, "mcp_server": SERVER}, ctx)
            assert exc_info.value.code == "BEDDEL-PRIM-304"
        assert log.count("call_tool") == 0

    async def test_registry_lookup_precedes_allowlist(self) -> None:
        client, _ = _client()
        ctx = _context(client, None)

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": TOOL, "mcp_server": "unknown_srv"}, ctx)

        assert exc_info.value.code == PRIM_MISSING_TOOL_REGISTRY == "BEDDEL-PRIM-005"
        assert exc_info.value.details["mcp_server"] == "unknown_srv"

    async def test_no_registry_keeps_prim_005_without_allowlist(self) -> None:
        ctx = make_context(tool_registry={}, metadata={})

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute(_config(), ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-005"

    async def test_local_suffix_rule_and_none_are_unchanged(self) -> None:
        def _fn() -> str:
            return "local"

        registry = {"ns:fn": _fn}
        ctx = make_context(tool_registry=registry, metadata={"_workflow_allowed_tools": ["fn"]})
        result = await ToolPrimitive().execute({"tool": "ns:fn"}, ctx)
        assert result["result"] == "local"

        ctx_none = make_context(tool_registry=registry, metadata={"_workflow_allowed_tools": None})
        assert (await ToolPrimitive().execute({"tool": "ns:fn"}, ctx_none))["result"] == "local"

        ctx_no_key = make_context(tool_registry=registry)
        assert (await ToolPrimitive().execute({"tool": "ns:fn"}, ctx_no_key))["result"] == "local"

        ctx_blocked = make_context(
            tool_registry=registry, metadata={"_workflow_allowed_tools": ["other"]}
        )
        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "ns:fn"}, ctx_blocked)
        assert exc_info.value.code == "BEDDEL-PRIM-304"
        assert "ns:fn" in exc_info.value.message  # local message is unchanged


# ---------------------------------------------------------------------------
# AC 13: error codes preserved, no raw exception text
# ---------------------------------------------------------------------------


class TestMCPErrorCodesPreserved:
    def test_every_mcp_code_is_covered(self) -> None:
        names = _mcp_codes()
        assert "MCP_AUTHORIZATION_REQUIRED" in names  # BEDDEL-MCP-605
        assert "MCP_SCHEMA_VALIDATION_FAILED" in names
        assert len(names) >= 6

    @pytest.mark.parametrize("name", _mcp_codes())
    async def test_call_tool_mcp_error_passes_through_unchanged(self, name: str) -> None:
        raised = MCPError(ALL_CODES[name], "client text", {"hint": "kept"})
        client, _ = _client(ClientScript(call_error=raised))

        with pytest.raises(MCPError) as exc_info:
            await ToolPrimitive().execute(_config(), _context(client, [QUALIFIED]))

        assert exc_info.value is raised
        assert exc_info.value.code == ALL_CODES[name]
        assert exc_info.value.code != PRIM_TOOL_EXEC_FAILED
        assert exc_info.value.details == {"hint": "kept"}

    @pytest.mark.parametrize("name", _mcp_codes())
    async def test_list_tools_mcp_error_passes_through_unchanged(self, name: str) -> None:
        raised = MCPError(ALL_CODES[name], "client text")
        client, log = _client(ClientScript(list_error=raised))

        with pytest.raises(MCPError) as exc_info:
            await ToolPrimitive(schema_validator=stub_validate_tool_arguments).execute(
                _config(validate_schema=True, arguments={"text": "x"}),
                _context(client, [QUALIFIED]),
            )

        assert exc_info.value is raised
        assert log.count("call_tool") == 0

    @pytest.mark.parametrize(
        "error",
        [
            PrimitiveError("BEDDEL-PRIM-999", "primitive text"),
            ParseError("BEDDEL-PARSE-999", "parse text"),
            BeddelError("BEDDEL-TEST-001", "base text"),
        ],
        ids=["primitive", "parse", "base"],
    )
    async def test_any_beddel_error_passes_through_unchanged(self, error: BeddelError) -> None:
        client, _ = _client(ClientScript(call_error=error))

        with pytest.raises(BeddelError) as exc_info:
            await ToolPrimitive().execute(_config(), _context(client, [QUALIFIED]))

        assert exc_info.value is error

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError(f"connection lost token={FAKE_SECRET_MARKER}"),
            OSError(f"socket {FAKE_SECRET_MARKER}"),
            ValueError(FAKE_SECRET_MARKER),
            KeyError(FAKE_SECRET_MARKER),
            Exception(FAKE_SECRET_MARKER),
        ],
        ids=lambda e: type(e).__name__,
    )
    async def test_other_exception_is_wrapped_without_raw_text(
        self, error: Exception, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        client, _ = _client(ClientScript(call_error=error))

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute(
                _config(arguments={"text": "x"}), _context(client, [QUALIFIED])
            )

        err = exc_info.value
        assert err.code == PRIM_TOOL_EXEC_FAILED == "BEDDEL-PRIM-301"
        assert err.message == CALL_FAILED_MESSAGE
        assert err.details == {"error_type": type(error).__name__}
        assert "original_error" not in err.details
        assert_unchained(err)
        assert_marker_absent(err, caplog)

    async def test_custom_exception_reports_only_its_class_name(self) -> None:
        class TransportBroke(Exception):
            pass

        client, _ = _client(ClientScript(call_error=TransportBroke(FAKE_SECRET_MARKER)))

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute(_config(), _context(client, [QUALIFIED]))

        assert exc_info.value.details == {"error_type": "TransportBroke"}
        assert_unchained(exc_info.value)
        assert_marker_absent(exc_info.value)

    async def test_timeout_keeps_prim_303_and_is_unchained(self) -> None:
        client, _ = _client(ClientScript(block_call=True))

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute(_config(timeout=0.05), _context(client, [QUALIFIED]))

        err = exc_info.value
        assert err.code == PRIM_TOOL_TIMEOUT == "BEDDEL-PRIM-303"
        assert err.details["timeout"] == 0.05
        assert_unchained(err)

    async def test_cancellation_is_not_swallowed(self) -> None:
        client, _ = _client(ClientScript(block_call=True))
        task = asyncio.create_task(
            ToolPrimitive().execute(_config(timeout=30), _context(client, [QUALIFIED]))
        )
        await asyncio.wait_for(client.call_started.wait(), timeout=5)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_list_tools_other_exception_is_wrapped_without_raw_text(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        error = RuntimeError(f"listing broke {FAKE_SECRET_MARKER}")
        client, log = _client(ClientScript(list_error=error))
        ctx = _context(client, [QUALIFIED])

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive(schema_validator=stub_validate_tool_arguments).execute(
                _config(validate_schema=True, arguments={"text": "x"}), ctx
            )

        err = exc_info.value
        assert err.code == "BEDDEL-PRIM-301"
        assert err.message == DISCOVERY_FAILED_MESSAGE
        assert err.details == {"error_type": "RuntimeError"}
        assert_unchained(err)
        assert_marker_absent(err, caplog)
        assert log.count("call_tool") == 0
        assert SERVER not in ctx.metadata.get("beddel._mcp_tool_schemas", {})

    async def test_malformed_tool_descriptor_is_wrapped(self) -> None:
        # A server-controlled descriptor without ``inputSchema`` must not leak a raw KeyError.
        client, log = _client(ClientScript(tools=[{"name": TOOL, "description": "no schema"}]))

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive(schema_validator=stub_validate_tool_arguments).execute(
                _config(validate_schema=True, arguments={"text": "x"}),
                _context(client, [QUALIFIED]),
            )

        assert exc_info.value.code == "BEDDEL-PRIM-301"
        assert exc_info.value.details == {"error_type": "KeyError"}
        assert_unchained(exc_info.value)
        assert log.count("call_tool") == 0


# ---------------------------------------------------------------------------
# AC 11: schema validator comes from the composition root
# ---------------------------------------------------------------------------


class TestMCPSchemaValidatorSeam:
    async def test_supplied_validator_is_the_one_called(self) -> None:
        seen: list[tuple[dict[str, Any], dict[str, Any]]] = []

        def _spy(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
            seen.append((arguments, schema))

        client, log = _client()
        ctx = _context(client, [f"{SERVER}:echo"])

        await ToolPrimitive(schema_validator=_spy).execute(
            {
                "tool": "echo",
                "mcp_server": SERVER,
                "validate_schema": True,
                "arguments": {"text": "hello"},
            },
            ctx,
        )

        assert len(seen) == 1
        assert seen[0][0] == {"text": "hello"}
        assert seen[0][1]["required"] == ["text"]
        assert log.names() == ["constructed", "connected", "list_tools", "call_tool"]

    async def test_register_builtins_hands_the_validator_to_the_tool_primitive(self) -> None:
        seen: list[dict[str, Any]] = []

        def _spy(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
            seen.append(arguments)

        registry = PrimitiveRegistry()
        register_builtins(registry, mcp_schema_validator=_spy)
        primitive = registry.get("tool")
        assert isinstance(primitive, ToolPrimitive)
        client, _ = _client()

        await primitive.execute(
            {
                "tool": "echo",
                "mcp_server": SERVER,
                "validate_schema": True,
                "arguments": {"text": "hi"},
            },
            _context(client, [f"{SERVER}:echo"]),
        )

        assert seen == [{"text": "hi"}]

    @pytest.mark.parametrize("via", ["constructor", "register_builtins"])
    async def test_without_validator_the_error_is_distinct_and_calls_nothing(
        self, via: str
    ) -> None:
        if via == "constructor":
            primitive: Any = ToolPrimitive()
        else:
            registry = PrimitiveRegistry()
            register_builtins(registry)  # one argument: unchanged call shape
            primitive = registry.get("tool")
        client, log = _client()

        with pytest.raises(PrimitiveError) as exc_info:
            await primitive.execute(
                _config(validate_schema=True, arguments={"text": "x"}),
                _context(client, [QUALIFIED]),
            )

        err = exc_info.value
        assert err.code == PRIM_TOOL_EXEC_FAILED
        assert "validator" in err.message
        assert "composition root" in err.message
        assert "jsonschema" not in err.message.lower()
        assert "jsonschema" not in repr(err.details).lower()
        assert err.details["reason"] == "schema_validator_unavailable"
        assert log.count("list_tools") == 0
        assert log.count("call_tool") == 0

    async def test_violating_arguments_are_rejected_before_the_call(self) -> None:
        client, log = _client()

        with pytest.raises(MCPError) as exc_info:
            await ToolPrimitive(schema_validator=stub_validate_tool_arguments).execute(
                {
                    "tool": "echo",
                    "mcp_server": SERVER,
                    "validate_schema": True,
                    "arguments": {"text": 12345},
                },
                _context(client, [f"{SERVER}:echo"]),
            )

        assert exc_info.value.code == MCP_SCHEMA_VALIDATION_FAILED == "BEDDEL-MCP-603"
        assert log.count("list_tools") == 1
        assert log.count("call_tool") == 0

    async def test_schema_cache_is_reused_across_calls(self) -> None:
        client, log = _client()
        ctx = _context(client, [f"{SERVER}:echo"])
        primitive = ToolPrimitive(schema_validator=stub_validate_tool_arguments)
        config = {
            "tool": "echo",
            "mcp_server": SERVER,
            "validate_schema": True,
            "arguments": {"text": "x"},
        }

        await primitive.execute(config, ctx)
        await primitive.execute(config, ctx)

        assert log.count("list_tools") == 1
        assert log.count("call_tool") == 2

    async def test_unknown_tool_is_reported_before_the_call(self) -> None:
        client, log = _client()

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive(schema_validator=stub_validate_tool_arguments).execute(
                _config(validate_schema=True, arguments={"text": "x"}),
                _context(client, [QUALIFIED]),
            )

        assert exc_info.value.code == "BEDDEL-PRIM-301"
        assert "schema discovery" in exc_info.value.message
        assert log.count("call_tool") == 0

    def test_tool_module_has_no_kit_import_and_no_path_computation(self) -> None:
        source = Path(tool_module.__file__ or "").read_text(encoding="utf-8")

        assert "parents[" not in source
        assert "sys.path" not in source
        assert "beddel_protocol_mcp" not in source
        assert "protocol-mcp-kit" not in source
        assert not re.search(r"^\s*(import|from)\s+(sys|pathlib)\b", source, re.MULTILINE)
        assert not hasattr(tool_module, "_validate_tool_arguments")
        assert not hasattr(tool_module, "_mcp_kit_dir")

    def test_importing_the_tool_module_leaves_sys_path_alone(self) -> None:
        # A fresh interpreter proves the import itself does not edit sys.path or import a kit.
        code = (
            "import sys, beddel\n"
            "before = list(sys.path)\n"
            "import beddel.primitives.tool\n"
            "assert sys.path == before, 'sys.path changed'\n"
            "assert 'beddel_protocol_mcp' not in sys.modules, 'kit imported'\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr


# ---------------------------------------------------------------------------
# Through the executor: the allowlist reaches the primitive and codes survive
# ---------------------------------------------------------------------------


class TestMCPEnforcementThroughExecutor:
    @staticmethod
    def _run(
        client: FakeMCPClient, allowed: list[str] | None, config: dict[str, Any] | None = None
    ) -> Any:
        registry = PrimitiveRegistry()
        register_builtins(registry, mcp_schema_validator=stub_validate_tool_arguments)
        deps = DefaultDependencies(mcp_registry={SERVER: client})
        workflow = Workflow(
            id="wf-mcp-enforce",
            name="MCP enforcement",
            steps=[Step(id="s1", primitive="tool", config=config or _config())],
            allowed_tools=allowed,
        )
        return WorkflowExecutor(registry, deps=deps).execute(workflow, {})

    async def test_workflow_without_allowlist_refuses_the_mcp_step(self) -> None:
        client, log = _client()

        with pytest.raises(ExecutionError) as exc_info:
            await self._run(client, None)

        cause = exc_info.value.__cause__
        assert isinstance(cause, PrimitiveError)
        assert cause.code == "BEDDEL-PRIM-304"
        assert log.names() == ["constructed"]

    async def test_allowlisted_step_runs(self) -> None:
        client, log = _client(ClientScript(call_result="ran"))

        result = await self._run(client, [QUALIFIED])

        assert result["step_results"]["s1"]["result"] == "ran"
        assert log.count("call_tool") == 1

    async def test_mcp_error_code_survives_the_executor(self) -> None:
        raised = MCPError(ALL_CODES["MCP_AUTHORIZATION_REQUIRED"], "operator action needed")
        client, _ = _client(ClientScript(call_error=raised))

        with pytest.raises(ExecutionError) as exc_info:
            await self._run(client, [QUALIFIED])

        assert exc_info.value.__cause__ is raised
        assert raised.code == "BEDDEL-MCP-605"
