"""Shared fakes for the MCP composition and enforcement tests (Story 1.2b).

``FakeMCPClient`` follows the construction and lifecycle contract of the
MCP protocol kit README (``Construction and lifecycle contract``):

1. The constructor takes ``transport``, ``endpoint`` and ``authorization`` by
   name, validates nothing that needs I/O and performs no I/O.
2. The first ``list_tools`` or ``call_tool`` connects.  The core never calls
   ``connect``; calling it is accepted only for the client's own endpoint
   (any other raises ``BEDDEL-MCP-600`` with a fixed message).
3. ``disconnect`` is safe whether or not a connection was made, repeatable
   and usable after a cancelled call.

The fake imports neither the kit nor the MCP SDK and uses no network and no
credential.  ``FAKE_SECRET_MARKER`` is an obviously fake string that tests
plant in exception text, arguments and endpoints, then assert it never leaks.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import traceback
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from beddel.domain.errors import BeddelError, MCPError
from beddel.error_codes import MCP_CONNECTION_FAILED, MCP_SCHEMA_VALIDATION_FAILED

FAKE_SECRET_MARKER = "FAKE-SECRET-MARKER"

DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Echo a string",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


@dataclass
class EventLog:
    """Ordered record of lifecycle events shared by every fake of one test."""

    events: list[tuple[str, str]] = field(default_factory=list)

    def record(self, event: str, detail: str = "") -> None:
        self.events.append((event, detail))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def count(self, event: str) -> int:
        return self.names().count(event)


@dataclass
class ClientScript:
    """Scripted behavior of one fake client (all defaults: a healthy server)."""

    tools: list[dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(DEFAULT_TOOLS))
    call_result: Any = field(default_factory=lambda: {"ok": True})
    list_error: BaseException | None = None
    call_error: BaseException | None = None
    disconnect_error: BaseException | None = None
    block_call: bool = False


class FakeMCPClient:
    """In-memory ``IMCPClient`` that follows the kit construction contract."""

    def __init__(
        self,
        transport: str,
        endpoint: str,
        authorization: str,
        *,
        log: EventLog | None = None,
        script: ClientScript | None = None,
    ) -> None:
        self.transport = transport
        self.endpoint = endpoint
        self.authorization = authorization
        self.log = log if log is not None else EventLog()
        self.script = script if script is not None else ClientScript()
        self.connected = False
        self.call_started = asyncio.Event()
        self.log.record("constructed", endpoint)

    async def connect(self, server_uri: str) -> None:
        if server_uri != self.endpoint:
            raise MCPError(MCP_CONNECTION_FAILED, "MCP connect refused for another endpoint")
        self._ensure_connected()

    async def list_tools(self) -> list[dict[str, Any]]:
        self._ensure_connected()
        self.log.record("list_tools")
        if self.script.list_error is not None:
            raise self.script.list_error
        return copy.deepcopy(self.script.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._ensure_connected()
        self.log.record("call_tool", name)
        self.call_started.set()
        if self.script.block_call:
            await asyncio.Event().wait()
        if self.script.call_error is not None:
            raise self.script.call_error
        return copy.deepcopy(self.script.call_result)

    async def disconnect(self) -> None:
        self.log.record("disconnected", self.endpoint)
        self.connected = False
        if self.script.disconnect_error is not None:
            raise self.script.disconnect_error

    def _ensure_connected(self) -> None:
        if not self.connected:
            self.connected = True
            self.log.record("connected", self.endpoint)


def make_fake_client_class(
    log: EventLog,
    scripts: dict[str, ClientScript] | None = None,
) -> type[FakeMCPClient]:
    """Return a constructor with the kit signature, bound to a shared log.

    The returned class accepts exactly ``transport``, ``endpoint`` and
    ``authorization`` (by name), like the kit adapter, so a composition root
    can register it as a per-transport constructor.  ``scripts`` maps an
    endpoint to its scripted behavior.
    """
    endpoint_scripts = scripts if scripts is not None else {}

    class _BoundFakeMCPClient(FakeMCPClient):
        def __init__(self, transport: str, endpoint: str, authorization: str) -> None:
            super().__init__(
                transport,
                endpoint,
                authorization,
                log=log,
                script=endpoint_scripts.get(endpoint, ClientScript()),
            )

    return _BoundFakeMCPClient


def stub_validate_tool_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    """Jsonschema-free stand-in for the kit validator.

    Checks ``required`` and string-typed ``properties`` only, and raises
    ``MCPError`` ``BEDDEL-MCP-603`` with a fixed message that never echoes a
    value, like the contract requires of the real validator's callers.
    """
    for name in schema.get("required", []):
        if name not in arguments:
            raise MCPError(MCP_SCHEMA_VALIDATION_FAILED, "Tool arguments failed schema validation")
    for name, spec in schema.get("properties", {}).items():
        if (
            name in arguments
            and spec.get("type") == "string"
            and not isinstance(arguments[name], str)
        ):
            raise MCPError(MCP_SCHEMA_VALIDATION_FAILED, "Tool arguments failed schema validation")


def iter_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and every exception reachable through cause or context."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        stack.append(current.__cause__)
        stack.append(current.__context__)


def exception_texts(exc: BaseException) -> list[str]:
    """Every textual surface of ``exc`` and of its cause/context chain."""
    texts: list[str] = []
    for item in iter_exception_chain(exc):
        texts.extend([str(item), repr(item), repr(item.args)])
        if isinstance(item, BeddelError):
            texts.extend([item.code, item.message, repr(item.details)])
    texts.append("".join(traceback.format_exception(exc)))
    return texts


def assert_marker_absent(
    exc: BaseException,
    caplog: Any = None,
    marker: str = FAKE_SECRET_MARKER,
) -> None:
    """Assert ``marker`` appears in no str, repr, message, details, chain or log."""
    for text in exception_texts(exc):
        assert marker not in text, "secret marker leaked through an exception surface"
    if caplog is not None:
        assert marker not in caplog.text, "secret marker leaked into a captured log"
        for record in caplog.records:
            assert marker not in record.getMessage()
            assert marker not in str(record.exc_text or "")
            assert record.exc_info is None or marker not in "".join(
                traceback.format_exception(*record.exc_info)
            )


def assert_unchained(exc: BaseException) -> None:
    """Assert neither ``__cause__`` nor ``__context__`` is set."""
    assert exc.__cause__ is None
    assert exc.__context__ is None


def enable_log_capture(caplog: Any) -> None:
    """Capture every logger at DEBUG so leaks into logs are observable."""
    caplog.set_level(logging.DEBUG)
