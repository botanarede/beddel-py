"""Tests for the surface composition of declared MCP servers (Story 1.2b, Task 4).

Covers AC 5 (static registration), AC 6 (one import location), AC 7 (one client
per named server, closed when the run ends), AC 11 (the validator comes from the
composition's kit module) and AC 14 (no I/O at composition, connect on first
use, step strategies keep working).

A fake kit following the kit README construction contract is written under
``tmp_path`` (``tests/_mcp_fakes.py::write_fake_kit``).  No network, no SDK, no
real kit and no credential are used; ``sys.modules`` and ``sys.path`` are
restored after every test.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from _mcp_fakes import (
    FAKE_KIT_STATE,
    FAKE_SECRET_MARKER,
    ClientScript,
    FakeKitState,
    FakeMCPClient,
    assert_marker_absent,
    assert_unchained,
    enable_log_capture,
    purge_kit_modules,
    reset_fake_kit_state,
    write_fake_kit,
)
from click.testing import CliRunner, Result

from beddel.cli import commands as commands_module
from beddel.cli import config as config_module
from beddel.cli import mcp_composition as surface
from beddel.cli.commands import run
from beddel.cli.mcp_composition import (
    KIT_MODULE,
    MCPWiring,
    compose_mcp,
    execute_and_close,
    load_kit_module,
    locate_kit_source,
)
from beddel.domain import mcp_composition as domain_composition
from beddel.domain.errors import ExecutionError, MCPError, PrimitiveError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.mcp_composition import (
    COMPOSITION_FAILED_MESSAGE,
    REASON_ADAPTER_CONSTRUCTION_FAILED,
    REASON_ADAPTER_UNAVAILABLE,
    REASON_KIT_AMBIGUOUS,
    REASON_KIT_LOCATION_MISMATCH,
    REASON_KIT_UNAVAILABLE,
    REASON_KITS_DISABLED,
    REASON_UNKNOWN_TRANSPORT,
)
from beddel.domain.models import DefaultDependencies, Workflow
from beddel.domain.registry import PrimitiveRegistry
from beddel.error_codes import (
    EXEC_COMPOSITION_FAILED,
    MCP_CONNECTION_FAILED,
)
from beddel.primitives import register_builtins

TRANSPORT = "mcp-streamable-http"
SERVER = "acme_srv"
SECOND = "other_srv"
ENDPOINT = "https://fake.example/mcp"
ENDPOINT2 = "https://other.example/mcp"
TOOL = "echo"
QUALIFIED = f"{SERVER}:{TOOL}"
QUALIFIED2 = f"{SECOND}:{TOOL}"

# Captured at import time, before the autouse fixture replaces it with a stub.
_REAL_ENSURE_KIT_PATHS = commands_module._ensure_kit_paths


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Fresh fake-kit state; sys.modules / sys.path restored; no real config read."""
    state = reset_fake_kit_state()
    purge_kit_modules()
    path_before = list(sys.path)
    # A real ``beddel_protocol_mcp`` reachable through ``sys.path`` (a kit installed, or put
    # on ``PYTHONPATH`` as tests/conftest.py intends) is imported by the adapter loader
    # before the composition runs, and the composition then correctly rejects it as a
    # module from another location.  These tests exercise their own fake kit, so hide
    # every other copy for the duration of the test; ``path_before`` restores it.
    sys.path[:] = [entry for entry in sys.path if not (Path(entry or ".") / KIT_MODULE).is_dir()]
    importlib.invalidate_caches()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "GLOBAL_CONFIG_PATH", tmp_path / "no-global-config.json")
    monkeypatch.setattr(commands_module, "_ensure_kit_paths", lambda: None)
    yield state
    purge_kit_modules()
    sys.path[:] = path_before
    reset_fake_kit_state()


def _server(endpoint: str = ENDPOINT, transport: str = TRANSPORT) -> dict[str, str]:
    return {"transport": transport, "endpoint": endpoint, "authorization": "none"}


def _step(
    step_id: str = "call",
    *,
    server: str = SERVER,
    tool: str = TOOL,
    arguments: dict[str, Any] | None = None,
    strategy: dict[str, Any] | None = None,
    **config: Any,
) -> dict[str, Any]:
    step_config: dict[str, Any] = {"mcp_server": server, "tool": tool, **config}
    if arguments is not None:
        step_config["arguments"] = arguments
    step: dict[str, Any] = {"id": step_id, "primitive": "tool", "config": step_config}
    if strategy is not None:
        step["execution_strategy"] = strategy
    return step


def _doc(
    steps: list[dict[str, Any]] | None = None,
    *,
    servers: dict[str, Any] | None = None,
    allowed: list[str] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "id": "wf",
        "name": "wf",
        "steps": steps if steps is not None else [_step()],
        "mcp_servers": servers if servers is not None else {SERVER: _server()},
        "allowed_tools": allowed if allowed is not None else [QUALIFIED],
    }
    return document


def _workflow(document: dict[str, Any] | None = None) -> Workflow:
    return Workflow.model_validate(document if document is not None else _doc())


def _kits(tmp_path: Path, name: str = "kits", **kwargs: Any) -> Path:
    kits_dir = tmp_path / name
    write_fake_kit(kits_dir, **kwargs)
    return kits_dir


def _compose(
    workflow: Workflow,
    wiring: MCPWiring,
    kits: Path | list[Path] | None,
    *,
    no_kits: bool = False,
    tool_names: tuple[str, ...] = (),
    kit_names: tuple[str, ...] = (),
) -> None:
    if kits is None:
        paths: list[Path] | None = None
    elif isinstance(kits, Path):
        paths = [kits]
    else:
        paths = kits
    compose_mcp(
        workflow,
        wiring,
        kit_paths=paths,
        no_kits=no_kits,
        tool_names=tool_names,
        kit_names=kit_names,
    )


def _composition_error(
    workflow: Workflow, kits: Path | list[Path] | None, **kwargs: Any
) -> ExecutionError:
    with pytest.raises(ExecutionError) as exc_info:
        _compose(workflow, MCPWiring(), kits, **kwargs)
    err = exc_info.value
    assert err.code == EXEC_COMPOSITION_FAILED
    assert err.message == COMPOSITION_FAILED_MESSAGE
    assert_unchained(err)
    return err


def _kit_modules() -> dict[str, Any]:
    return {
        name: module
        for name, module in sys.modules.items()
        if name == KIT_MODULE or name.startswith(f"{KIT_MODULE}.")
    }


def _write_workflow(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "wf.yaml"
    path.write_text(yaml.safe_dump(document))
    return path


def _invoke(
    tmp_path: Path,
    document: dict[str, Any],
    *,
    kits: list[Path] | None = None,
    extra: tuple[str, ...] = (),
) -> Result:
    args = [str(_write_workflow(tmp_path, document)), "--json-output"]
    for kit_dir in kits or []:
        args += ["--kit", str(kit_dir)]
    args += list(extra)
    return CliRunner().invoke(run, args)


def _step_results(result: Result) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


class _StubExecutor:
    """Executor stand-in: records the call, then returns, raises or blocks."""

    def __init__(self, *, error: BaseException | None = None, block: bool = False) -> None:
        self.error = error
        self.block = block
        self.started = asyncio.Event()

    async def execute(self, workflow: Workflow, inputs: dict[str, Any]) -> dict[str, Any]:
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return {"step_results": {}}


def _wiring_with(
    state: FakeKitState, *endpoints: str, scripts: dict[str, ClientScript] | None
) -> MCPWiring:
    wiring = MCPWiring()
    for index, endpoint in enumerate(endpoints):
        client = FakeMCPClient(
            TRANSPORT,
            endpoint,
            "none",
            log=state.log,
            script=(scripts or {}).get(endpoint),
        )
        wiring.add(f"srv_{index}", client)
    return wiring


# ---------------------------------------------------------------------------
# AC 5: static, explicit registration
# ---------------------------------------------------------------------------


class TestStaticRegistration:
    def test_registry_is_the_static_enumeration_keyed_by_transport(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        wiring = MCPWiring()

        _compose(_workflow(), wiring, kits)

        module = sys.modules[KIT_MODULE]
        assert surface.MCP_CLIENT_ADAPTERS == (("mcp-streamable-http", "StreamableHTTPMCPClient"),)
        assert surface._registered_constructors(module) == {
            "mcp-streamable-http": module.StreamableHTTPMCPClient
        }
        assert list(wiring.registry or {}) == [SERVER]

    def test_stdio_and_sse_adapters_are_never_registered_or_constructed(
        self, tmp_path: Path
    ) -> None:
        kits = _kits(tmp_path)
        _compose(_workflow(), MCPWiring(), kits)
        module = sys.modules[KIT_MODULE]

        constructors = surface._registered_constructors(module)

        assert set(constructors) == {"mcp-streamable-http"}
        assert module.StdioMCPClient not in constructors.values()
        assert module.SSEMCPClient not in constructors.values()

    @pytest.mark.parametrize("transport", ["mcp-stdio", "mcp-sse"])
    def test_a_declaration_for_a_kit_supplied_but_unregistered_transport_is_rejected(
        self, tmp_path: Path, transport: str
    ) -> None:
        kits = _kits(tmp_path)
        document = _doc(servers={SERVER: _server(transport=transport)})

        err = _composition_error(_workflow(document), kits)

        assert err.details["reason"] == REASON_UNKNOWN_TRANSPORT
        assert FAKE_KIT_STATE.constructor_kwargs == []

    def test_no_other_kits_mcp_adapter_is_registered(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        other = kits / "other-mcp-kit"
        (other / "python" / "other_mcp_pkg").mkdir(parents=True)
        (other / "python" / "other_mcp_pkg" / "__init__.py").write_text(
            "class OtherClient:\n    def __init__(self, **kwargs):\n        raise AssertionError\n"
        )
        (other / "kit.yaml").write_text(
            "name: other-mcp-kit\nversion: 0.0.0\ndescription: x\nauthor: t\n"
            "targets:\n  python:\n    status: implemented\n    module: other_mcp_pkg\n"
            "    adapters:\n    - port: IMCPClient\n      name: mcp-other\n"
            "      target: other_mcp_pkg:OtherClient\n"
        )
        document = _doc(servers={SERVER: _server(transport="mcp-other")})

        err = _composition_error(_workflow(document), kits)

        assert err.details["reason"] == REASON_UNKNOWN_TRANSPORT

    def test_constructors_receive_the_three_fields_as_keywords(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        document = _doc(servers={SERVER: _server(endpoint=ENDPOINT)})

        _compose(_workflow(document), MCPWiring(), kits)

        # The fake constructor is keyword-only: a positional call would raise TypeError.
        assert FAKE_KIT_STATE.constructor_kwargs == [
            {"transport": TRANSPORT, "endpoint": ENDPOINT, "authorization": "none"}
        ]

    def test_the_composition_never_uses_discovery_or_the_zero_argument_loader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import beddel.tools.kits as kits_module

        def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("kit discovery / adapter loader must not run in the composition")

        monkeypatch.setattr(kits_module, "load_kit_adapters", _forbidden)
        monkeypatch.setattr(kits_module, "discover_kits", _forbidden)
        monkeypatch.setattr(kits_module, "load_kit", _forbidden)

        _compose(_workflow(), MCPWiring(), _kits(tmp_path))

        names: set[str] = set()
        for node in ast.walk(ast.parse(inspect.getsource(surface))):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        assert not names & {"load_kit_adapters", "discover_kits", "load_kit"}
        assert not names & {
            "_build_adapter_registries",
            "_ensure_kit_paths",
            "_add_kit_dir_to_path",
        }

    def test_the_composition_never_edits_sys_path(self) -> None:
        mutating = {"insert", "append", "extend", "remove", "pop", "clear", "__setitem__"}
        tree = ast.parse(inspect.getsource(surface))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in mutating
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "path"
            ):
                pytest.fail("the composition must not edit sys.path")


# ---------------------------------------------------------------------------
# AC 6: one import location
# ---------------------------------------------------------------------------


class TestKitLocation:
    def test_module_is_loaded_from_the_configured_location(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        source = (kits / "protocol-mcp-kit" / "python").resolve()
        wiring = MCPWiring()

        _compose(_workflow(), wiring, kits)

        module = sys.modules[KIT_MODULE]
        assert Path(module.__file__).resolve().is_relative_to(source)
        assert wiring.schema_validator is module.validate_tool_arguments
        assert isinstance(wiring.registry[SERVER], module.StreamableHTTPMCPClient)  # type: ignore[index]

    def test_src_layout_is_used_when_there_is_no_python_directory(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path, layout="src")

        _compose(_workflow(), MCPWiring(), kits)

        assert "/src/" in Path(sys.modules[KIT_MODULE].__file__).as_posix()

    def test_python_directory_wins_over_src(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        write_fake_kit(
            kits, layout="src", modules={"__init__.py": "raise SystemError('wrong dir')"}
        )

        _compose(_workflow(), MCPWiring(), kits)

        assert "/python/" in Path(sys.modules[KIT_MODULE].__file__).as_posix()

    def test_preloaded_by_the_loader_path_from_the_same_location_is_accepted(
        self, tmp_path: Path
    ) -> None:
        # Beddel's own loader normally imports the kit first (sys.path based).
        kits = _kits(tmp_path)
        source = kits / "protocol-mcp-kit" / "python"
        sys.path.insert(0, str(source))
        preloaded = importlib.import_module(KIT_MODULE)
        executions = list(FAKE_KIT_STATE.module_executions)
        path_before = list(sys.path)
        modules_before = dict(_kit_modules())
        wiring = MCPWiring()

        _compose(_workflow(), wiring, kits)

        assert sys.modules[KIT_MODULE] is preloaded
        assert FAKE_KIT_STATE.module_executions == executions  # not reloaded, not re-executed
        assert _kit_modules() == modules_before  # nothing deleted or replaced
        assert sys.path == path_before
        assert wiring.schema_validator is preloaded.validate_tool_arguments

    def test_preloaded_through_a_symlinked_path_is_accepted(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        link = tmp_path / "kit-link"
        link.symlink_to(kits / "protocol-mcp-kit", target_is_directory=True)
        sys.path.insert(0, str(link / "python"))
        preloaded = importlib.import_module(KIT_MODULE)
        assert "kit-link" in Path(preloaded.__file__).as_posix()

        _compose(_workflow(), MCPWiring(), kits)

        assert sys.modules[KIT_MODULE] is preloaded

    def test_a_symlinked_kits_directory_resolves(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        link = tmp_path / "kits-link"
        link.symlink_to(kits, target_is_directory=True)

        _compose(_workflow(), MCPWiring(), link)

        assert (
            Path(sys.modules[KIT_MODULE].__file__)
            .resolve()
            .is_relative_to((kits / "protocol-mcp-kit" / "python").resolve())
        )

    def test_the_same_location_reached_twice_is_not_ambiguous(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        link = tmp_path / "kits-link"
        link.symlink_to(kits, target_is_directory=True)

        wiring = MCPWiring()

        _compose(_workflow(), wiring, [kits, link, kits])

        assert list(wiring.registry or {}) == [SERVER]

    def test_module_already_loaded_from_another_directory_is_a_mismatch(
        self, tmp_path: Path
    ) -> None:
        decoy_source = write_fake_kit(tmp_path / "decoy-kits")
        sys.path.insert(0, str(decoy_source))
        decoy = importlib.import_module(KIT_MODULE)
        kits = _kits(tmp_path)
        wiring = MCPWiring()
        path_before = list(sys.path)

        with pytest.raises(ExecutionError) as exc_info:
            _compose(_workflow(), wiring, kits)

        assert exc_info.value.details["reason"] == REASON_KIT_LOCATION_MISMATCH
        assert exc_info.value.message == COMPOSITION_FAILED_MESSAGE
        assert sys.modules[KIT_MODULE] is decoy  # never deleted, never replaced
        assert sys.path == path_before
        assert not wiring.has_clients
        assert FAKE_KIT_STATE.constructor_kwargs == []

    def test_a_module_without_an_origin_is_a_mismatch(self, tmp_path: Path) -> None:
        import types

        sys.modules[KIT_MODULE] = types.ModuleType(KIT_MODULE)

        err = _composition_error(_workflow(), _kits(tmp_path))

        assert err.details["reason"] == REASON_KIT_LOCATION_MISMATCH

    def test_a_decoy_on_sys_path_is_ignored(self, tmp_path: Path) -> None:
        decoy_source = write_fake_kit(
            tmp_path / "decoy-kits", modules={"__init__.py": "raise SystemError('decoy used')"}
        )
        sys.path.insert(0, str(decoy_source))
        kits = _kits(tmp_path)
        path_before = list(sys.path)

        _compose(_workflow(), MCPWiring(), kits)

        loaded = Path(sys.modules[KIT_MODULE].__file__).resolve()
        assert loaded.is_relative_to((kits / "protocol-mcp-kit" / "python").resolve())
        assert not loaded.is_relative_to(decoy_source.resolve())
        assert sys.path == path_before

    @pytest.mark.parametrize("variant", ["none", "empty", "no_kit_dir", "no_source", "not_a_dir"])
    def test_no_kit_location_is_a_composition_error(self, tmp_path: Path, variant: str) -> None:
        kits: Path | list[Path] | None
        if variant == "none":
            kits = None
        elif variant == "empty":
            kits = []
        elif variant == "no_kit_dir":
            (tmp_path / "kits").mkdir()
            kits = tmp_path / "kits"
        elif variant == "no_source":
            (tmp_path / "kits" / "protocol-mcp-kit").mkdir(parents=True)
            kits = tmp_path / "kits"
        else:
            kits = tmp_path / "missing"

        err = _composition_error(_workflow(), kits)

        assert err.details["reason"] == REASON_KIT_UNAVAILABLE
        assert KIT_MODULE not in sys.modules

    def test_two_kit_locations_are_ambiguous(self, tmp_path: Path) -> None:
        first = _kits(tmp_path, "kits-a")
        second = _kits(tmp_path, "kits-b")

        err = _composition_error(_workflow(), [first, second])

        assert err.details["reason"] == REASON_KIT_AMBIGUOUS
        assert KIT_MODULE not in sys.modules
        assert FAKE_KIT_STATE.constructor_kwargs == []

    def test_an_import_failure_reports_only_the_class_name(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        kits = _kits(
            tmp_path, modules={"__init__.py": f"raise RuntimeError('{FAKE_SECRET_MARKER}')"}
        )

        err = _composition_error(_workflow(), kits)

        assert err.details == {"reason": REASON_KIT_UNAVAILABLE, "error_type": "RuntimeError"}
        assert_marker_absent(err, caplog)
        assert KIT_MODULE not in sys.modules  # the half-initialized entry is removed

    def test_a_missing_adapter_attribute_is_an_adapter_error_for_its_declarations(
        self, tmp_path: Path
    ) -> None:
        kits = _kits(tmp_path, modules={"__init__.py": "def validate_tool_arguments(a, s): ..."})

        err = _composition_error(_workflow(), kits)

        assert err.details == {
            "reason": REASON_ADAPTER_UNAVAILABLE,
            "field": "transport",
            "server": SERVER,
        }

    def test_a_missing_validator_is_not_a_composition_error(self, tmp_path: Path) -> None:
        kits = _kits(
            tmp_path,
            modules={
                "__init__.py": (
                    "from beddel_protocol_mcp.http_client import StreamableHTTPMCPClient\n"
                )
            },
        )
        wiring = MCPWiring()

        _compose(_workflow(), wiring, kits)

        assert wiring.schema_validator is None
        assert list(wiring.registry or {}) == [SERVER]

    def test_no_kit_import_for_a_workflow_without_mcp(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)
        document = {"id": "wf", "name": "wf", "steps": [{"id": "s", "primitive": "noop"}]}
        wiring = MCPWiring()

        _compose(_workflow(document), wiring, kits)

        assert KIT_MODULE not in sys.modules
        assert FAKE_KIT_STATE.module_executions == []
        assert wiring.registry is None
        assert wiring.schema_validator is None

    def test_a_declared_but_empty_server_map_imports_the_kit_and_builds_nothing(
        self, tmp_path: Path
    ) -> None:
        document = {"id": "wf", "name": "wf", "steps": [], "mcp_servers": {}, "allowed_tools": []}
        wiring = MCPWiring()

        _compose(_workflow(document), wiring, _kits(tmp_path))

        assert KIT_MODULE in sys.modules
        assert wiring.registry is None

    def test_no_kits_makes_any_mcp_use_a_composition_error(self, tmp_path: Path) -> None:
        err = _composition_error(_workflow(), _kits(tmp_path), no_kits=True)

        assert err.details == {"reason": REASON_KITS_DISABLED}
        assert KIT_MODULE not in sys.modules

    def test_no_kits_leaves_a_workflow_without_mcp_alone(self, tmp_path: Path) -> None:
        document = {"id": "wf", "name": "wf", "steps": [{"id": "s", "primitive": "noop"}]}

        _compose(_workflow(document), MCPWiring(), None, no_kits=True)

    def test_locate_and_load_are_usable_on_their_own(self, tmp_path: Path) -> None:
        kits = _kits(tmp_path)

        source = locate_kit_source([kits])
        module = load_kit_module(source)

        assert source == (kits / "protocol-mcp-kit" / "python").resolve()
        assert module is sys.modules[KIT_MODULE]


# ---------------------------------------------------------------------------
# AC 7: one client per named server; constructor failures
# ---------------------------------------------------------------------------


class TestClientConstruction:
    def test_declared_but_unnamed_servers_are_not_built(self, tmp_path: Path) -> None:
        document = _doc(
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED],
        )
        wiring = MCPWiring()

        _compose(_workflow(document), wiring, _kits(tmp_path))

        assert list(wiring.registry or {}) == [SERVER]
        assert [kw["endpoint"] for kw in FAKE_KIT_STATE.constructor_kwargs] == [ENDPOINT]
        assert FAKE_KIT_STATE.log.names() == ["constructed"]

    def test_one_client_per_named_server(self, tmp_path: Path) -> None:
        document = _doc(
            [_step("a"), _step("b", server=SECOND), _step("c")],
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED, QUALIFIED2],
        )
        wiring = MCPWiring()

        _compose(_workflow(document), wiring, _kits(tmp_path))

        assert list(wiring.registry or {}) == [SERVER, SECOND]
        assert len(FAKE_KIT_STATE.constructor_kwargs) == 2

    def test_construction_performs_no_io(self, tmp_path: Path) -> None:
        _compose(_workflow(), MCPWiring(), _kits(tmp_path))

        assert FAKE_KIT_STATE.log.names() == ["constructed"]

    def test_a_kit_mcp_error_propagates_unchanged(self, tmp_path: Path) -> None:
        raised = MCPError(MCP_CONNECTION_FAILED, "Unknown authorization method", {"hint": "x"})
        FAKE_KIT_STATE.constructor_errors[ENDPOINT] = raised

        with pytest.raises(MCPError) as exc_info:
            _compose(_workflow(), MCPWiring(), _kits(tmp_path))

        assert exc_info.value is raised
        assert exc_info.value.code == "BEDDEL-MCP-600"
        assert exc_info.value.details == {"hint": "x"}

    def test_any_other_constructor_exception_becomes_a_composition_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        FAKE_KIT_STATE.constructor_errors[ENDPOINT] = RuntimeError(f"boom {FAKE_SECRET_MARKER}")

        err = _composition_error(_workflow(), _kits(tmp_path))

        assert err.details == {
            "reason": REASON_ADAPTER_CONSTRUCTION_FAILED,
            "field": "transport",
            "server": SERVER,
            "error_type": "RuntimeError",
        }
        assert err.__cause__ is None
        assert err.__context__ is None
        assert_marker_absent(err, caplog)

    def test_a_non_mcp_beddel_error_from_a_constructor_is_also_wrapped(
        self, tmp_path: Path
    ) -> None:
        FAKE_KIT_STATE.constructor_errors[ENDPOINT] = PrimitiveError("BEDDEL-PRIM-999", "text")

        err = _composition_error(_workflow(), _kits(tmp_path))

        assert err.details["reason"] == REASON_ADAPTER_CONSTRUCTION_FAILED
        assert err.details["error_type"] == "PrimitiveError"

    async def test_clients_built_before_a_failing_constructor_are_closed_once(
        self, tmp_path: Path
    ) -> None:
        document = _doc(
            [_step("a"), _step("b", server=SECOND)],
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED, QUALIFIED2],
        )
        FAKE_KIT_STATE.constructor_errors[ENDPOINT2] = RuntimeError("boom")
        wiring = MCPWiring()

        with pytest.raises(ExecutionError):
            _compose(_workflow(document), wiring, _kits(tmp_path))
        assert wiring.has_clients
        await wiring.aclose()
        await wiring.aclose()

        assert FAKE_KIT_STATE.log.names() == ["constructed", "disconnected"]
        assert FAKE_KIT_STATE.log.events[-1] == ("disconnected", ENDPOINT)


# ---------------------------------------------------------------------------
# AC 7: disconnect when the run ends (success, failure, cancellation)
# ---------------------------------------------------------------------------


def _disconnects(state: FakeKitState) -> list[str]:
    return [detail for name, detail in state.log.events if name == "disconnected"]


class TestClientLifecycle:
    async def test_clients_are_disconnected_once_on_success(self, isolated: FakeKitState) -> None:
        wiring = _wiring_with(isolated, ENDPOINT, ENDPOINT2, scripts=None)

        result = await execute_and_close(_StubExecutor(), _workflow(), {}, wiring)  # type: ignore[arg-type]

        assert result == {"step_results": {}}
        assert sorted(_disconnects(isolated)) == sorted([ENDPOINT, ENDPOINT2])
        assert wiring.has_clients is False

    async def test_clients_are_disconnected_once_on_step_failure(
        self, isolated: FakeKitState
    ) -> None:
        wiring = _wiring_with(isolated, ENDPOINT, ENDPOINT2, scripts=None)
        failure = ExecutionError("BEDDEL-EXEC-002", "step failed")

        with pytest.raises(ExecutionError) as exc_info:
            await execute_and_close(_StubExecutor(error=failure), _workflow(), {}, wiring)  # type: ignore[arg-type]

        assert exc_info.value is failure
        assert sorted(_disconnects(isolated)) == sorted([ENDPOINT, ENDPOINT2])

    async def test_clients_are_disconnected_once_on_cancellation(
        self, isolated: FakeKitState
    ) -> None:
        wiring = _wiring_with(isolated, ENDPOINT, ENDPOINT2, scripts=None)
        executor = _StubExecutor(block=True)
        task = asyncio.create_task(execute_and_close(executor, _workflow(), {}, wiring))  # type: ignore[arg-type]
        await asyncio.wait_for(executor.started.wait(), timeout=5)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert sorted(_disconnects(isolated)) == sorted([ENDPOINT, ENDPOINT2])

    async def test_cancellation_mid_call_closes_the_connected_client(
        self, tmp_path: Path, isolated: FakeKitState
    ) -> None:
        isolated.scripts[ENDPOINT] = ClientScript(block_call=True)
        wiring = MCPWiring()
        _compose(_workflow(), wiring, _kits(tmp_path))
        registry = PrimitiveRegistry()
        register_builtins(registry, mcp_schema_validator=wiring.schema_validator)
        deps = DefaultDependencies(
            tool_registry={}, registry=registry, mcp_registry=wiring.registry
        )
        executor = WorkflowExecutor(registry, deps=deps)
        client = (wiring.registry or {})[SERVER]
        assert isinstance(client, FakeMCPClient)
        task = asyncio.create_task(execute_and_close(executor, _workflow(), {}, wiring))
        await asyncio.wait_for(client.call_started.wait(), timeout=5)
        assert client.connected is True

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert _disconnects(isolated) == [ENDPOINT]
        assert client.connected is False

    async def test_a_raising_disconnect_neither_masks_the_error_nor_skips_the_others(
        self, isolated: FakeKitState, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        scripts = {
            ENDPOINT: ClientScript(disconnect_error=RuntimeError(f"x {FAKE_SECRET_MARKER}"))
        }
        wiring = _wiring_with(isolated, ENDPOINT, ENDPOINT2, scripts=scripts)
        failure = ExecutionError("BEDDEL-EXEC-002", "step failed")

        with pytest.raises(ExecutionError) as exc_info:
            await execute_and_close(_StubExecutor(error=failure), _workflow(), {}, wiring)  # type: ignore[arg-type]

        assert exc_info.value is failure
        assert sorted(_disconnects(isolated)) == sorted([ENDPOINT, ENDPOINT2])
        assert FAKE_SECRET_MARKER not in caplog.text
        assert "RuntimeError" in caplog.text
        assert "srv_0" in caplog.text
        assert_marker_absent(exc_info.value, caplog)

    async def test_a_raising_disconnect_does_not_fail_a_successful_run(
        self, isolated: FakeKitState
    ) -> None:
        scripts = {ENDPOINT2: ClientScript(disconnect_error=OSError("gone"))}
        wiring = _wiring_with(isolated, ENDPOINT, ENDPOINT2, scripts=scripts)

        result = await execute_and_close(_StubExecutor(), _workflow(), {}, wiring)  # type: ignore[arg-type]

        assert result == {"step_results": {}}
        assert len(_disconnects(isolated)) == 2

    async def test_a_cancelled_disconnect_still_lets_the_others_close(
        self, isolated: FakeKitState
    ) -> None:
        scripts = {ENDPOINT: ClientScript(disconnect_error=asyncio.CancelledError())}
        wiring = _wiring_with(isolated, ENDPOINT, ENDPOINT2, scripts=scripts)

        with pytest.raises(asyncio.CancelledError):
            await wiring.aclose()

        assert sorted(_disconnects(isolated)) == sorted([ENDPOINT, ENDPOINT2])

    async def test_a_never_connected_client_disconnects_safely_and_only_once(
        self, isolated: FakeKitState
    ) -> None:
        wiring = _wiring_with(isolated, ENDPOINT, scripts=None)

        await wiring.aclose()
        await wiring.aclose()

        assert isolated.log.names() == ["constructed", "disconnected"]
        assert "connected" not in isolated.log.names()

    async def test_the_core_never_calls_connect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated: FakeKitState
    ) -> None:
        async def _forbidden(self: FakeMCPClient, server_uri: str) -> None:
            raise AssertionError("the core must never call connect")

        monkeypatch.setattr(FakeMCPClient, "connect", _forbidden)
        wiring = MCPWiring()
        _compose(_workflow(_doc([_step(arguments={"text": "x"})])), wiring, _kits(tmp_path))
        registry = PrimitiveRegistry()
        register_builtins(registry, mcp_schema_validator=wiring.schema_validator)
        deps = DefaultDependencies(
            tool_registry={}, registry=registry, mcp_registry=wiring.registry
        )

        result = await execute_and_close(
            WorkflowExecutor(registry, deps=deps),
            _workflow(_doc([_step(arguments={"text": "x"})])),
            {},
            wiring,
        )

        assert result["step_results"]["call"]["result"] == {"ok": True}
        assert isolated.log.names() == ["constructed", "connected", "call_tool", "disconnected"]


# ---------------------------------------------------------------------------
# beddel run end to end: composition errors, AC 11, AC 14
# ---------------------------------------------------------------------------


class TestRunCompositionErrors:
    def test_composition_error_prints_code_and_fixed_message_and_exits_1(
        self, tmp_path: Path
    ) -> None:
        document = _doc([_step(server="ghost_srv")])

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert f"Error [{EXEC_COMPOSITION_FAILED}]: {COMPOSITION_FAILED_MESSAGE}" in result.stderr
        for leak in ("reason", "undeclared_server", "ghost_srv", "step_id", "mcp_server"):
            assert leak not in result.output
        assert FAKE_KIT_STATE.constructor_kwargs == []  # nothing built, no step ran
        assert "call_tool" not in FAKE_KIT_STATE.log.names()

    def test_allowlist_violation_stops_the_run_before_any_step(self, tmp_path: Path) -> None:
        document = _doc(allowed=["acme_srv:other"])

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert EXEC_COMPOSITION_FAILED in result.stderr
        assert FAKE_KIT_STATE.log.events == []

    def test_missing_allowlist_is_a_composition_error(self, tmp_path: Path) -> None:
        document = _doc()
        del document["allowed_tools"]

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert EXEC_COMPOSITION_FAILED in result.stderr

    def test_no_kits_with_mcp_is_a_composition_error(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, _doc(), kits=[_kits(tmp_path)], extra=("--no-kits",))

        assert result.exit_code == 1
        assert f"Error [{EXEC_COMPOSITION_FAILED}]" in result.stderr
        assert KIT_MODULE not in sys.modules

    def test_missing_kit_is_a_composition_error(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, _doc())

        assert result.exit_code == 1
        assert f"Error [{EXEC_COMPOSITION_FAILED}]" in result.stderr

    def test_a_kit_constructor_mcp_error_is_printed_with_its_own_code(
        self, tmp_path: Path
    ) -> None:
        FAKE_KIT_STATE.constructor_errors[ENDPOINT] = MCPError(
            MCP_CONNECTION_FAILED, "Unknown authorization method"
        )

        result = _invoke(tmp_path, _doc(), kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert "Error [BEDDEL-MCP-600]: Unknown authorization method" in result.stderr

    def test_a_partial_construction_failure_closes_the_clients_built_so_far(
        self, tmp_path: Path
    ) -> None:
        document = _doc(
            [_step("a"), _step("b", server=SECOND)],
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED, QUALIFIED2],
        )
        FAKE_KIT_STATE.constructor_errors[ENDPOINT2] = RuntimeError("boom")

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert _disconnects(FAKE_KIT_STATE) == [ENDPOINT]


class TestRunHappyPathAndLifecycle:
    def test_run_wires_connects_on_first_use_and_disconnects_once(self, tmp_path: Path) -> None:
        document = _doc([_step(arguments={"text": "hi"})])

        steps = _step_results(_invoke(tmp_path, document, kits=[_kits(tmp_path)]))

        assert steps["call"]["result"] == {"ok": True}
        assert steps["call"]["mcp_server"] == SERVER
        assert FAKE_KIT_STATE.log.names() == [
            "constructed",
            "connected",
            "call_tool",
            "disconnected",
        ]

    def test_zero_io_before_the_first_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[tuple[str, str]]] = []
        original = surface.execute_and_close

        async def _spy(*args: Any, **kwargs: Any) -> Any:
            seen.append(list(FAKE_KIT_STATE.log.events))
            return await original(*args, **kwargs)

        monkeypatch.setattr(surface, "execute_and_close", _spy)

        _step_results(_invoke(tmp_path, _doc(), kits=[_kits(tmp_path)]))

        assert seen == [[("constructed", ENDPOINT)]]

    def test_the_run_fails_closed_without_executing_when_a_step_is_not_allowed(
        self, tmp_path: Path
    ) -> None:
        document = _doc([_step(tool="forbidden")])

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert "call_tool" not in FAKE_KIT_STATE.log.names()

    def test_step_failure_ends_the_run_and_still_disconnects(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = ClientScript(
            call_error=MCPError(MCP_CONNECTION_FAILED, "Unreachable MCP server")
        )

        result = _invoke(tmp_path, _doc(), kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert "Execution error [BEDDEL-EXEC-002]" in result.stderr
        assert _disconnects(FAKE_KIT_STATE) == [ENDPOINT]

    def test_cancellation_inside_the_run_still_disconnects(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = ClientScript(call_error=asyncio.CancelledError())

        # CancelledError is a BaseException: it leaves the CLI runner and the run.
        with pytest.raises(asyncio.CancelledError):
            _invoke(tmp_path, _doc(), kits=[_kits(tmp_path)])

        assert _disconnects(FAKE_KIT_STATE) == [ENDPOINT]

    def test_a_raising_disconnect_is_isolated_in_a_real_run(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        enable_log_capture(caplog)
        FAKE_KIT_STATE.scripts[ENDPOINT] = ClientScript(
            disconnect_error=RuntimeError(f"close {FAKE_SECRET_MARKER}")
        )

        steps = _step_results(_invoke(tmp_path, _doc(), kits=[_kits(tmp_path)]))

        assert steps["call"]["result"] == {"ok": True}
        assert FAKE_SECRET_MARKER not in caplog.text
        assert FAKE_SECRET_MARKER not in json.dumps(steps)

    def test_a_declared_but_never_used_branch_leaves_the_client_unconnected(
        self, tmp_path: Path
    ) -> None:
        document = _doc(
            [
                {
                    "id": "gate",
                    "primitive": "tool",
                    "if": "$input.go == 'yes'",
                    "config": {"tool": "unused"},
                    "then": [_step("inner")],
                }
            ]
        )

        _step_results(_invoke(tmp_path, document, kits=[_kits(tmp_path)]))

        assert FAKE_KIT_STATE.log.names() == ["constructed", "disconnected"]

    def test_workflow_without_mcp_behaves_as_before_and_imports_no_kit(
        self, tmp_path: Path
    ) -> None:
        document = {
            "id": "wf",
            "name": "wf",
            "steps": [
                {
                    "id": "local",
                    "primitive": "tool",
                    "config": {"tool": "dump", "arguments": {"obj": {"a": 1}}},
                }
            ],
        }

        result = _invoke(
            tmp_path, document, kits=[_kits(tmp_path)], extra=("--tool", "dump=json:dumps")
        )

        steps = _step_results(result)
        assert json.loads(steps["local"]["result"]) == {"a": 1}
        assert KIT_MODULE not in sys.modules
        assert FAKE_KIT_STATE.module_executions == []
        assert FAKE_KIT_STATE.log.events == []


class TestRunStrategies:
    """An unreachable server fails only the call that uses it (AC 14)."""

    @staticmethod
    def _unreachable() -> ClientScript:
        return ClientScript(call_error=MCPError(MCP_CONNECTION_FAILED, "Unreachable MCP server"))

    def _two_server_document(self, strategy: dict[str, Any] | None) -> dict[str, Any]:
        return _doc(
            [
                _step("first", strategy=strategy),
                _step("second", server=SECOND, arguments={"text": "ok"}),
            ],
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED, QUALIFIED2],
        )

    def test_skip_continues_with_the_next_step(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = self._unreachable()
        document = self._two_server_document({"type": "skip"})

        steps = _step_results(_invoke(tmp_path, document, kits=[_kits(tmp_path)]))

        assert steps["second"]["result"] == {"ok": True}
        assert sorted(_disconnects(FAKE_KIT_STATE)) == sorted([ENDPOINT, ENDPOINT2])

    def test_fail_stops_the_run_at_that_step(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = self._unreachable()
        document = self._two_server_document({"type": "fail"})

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert "Execution error [BEDDEL-EXEC-002]" in result.stderr
        calls = [detail for name, detail in FAKE_KIT_STATE.log.events if name == "call_tool"]
        assert calls == [TOOL]  # the second step never ran
        assert sorted(_disconnects(FAKE_KIT_STATE)) == sorted([ENDPOINT, ENDPOINT2])

    def test_retry_runs_the_step_again_and_then_gives_up(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = self._unreachable()
        strategy = {
            "type": "retry",
            "retry": {"max_attempts": 2, "backoff_base": 0, "backoff_max": 0, "jitter": False},
        }

        result = _invoke(tmp_path, self._two_server_document(strategy), kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert "BEDDEL-EXEC-003" in result.stderr
        calls = [detail for name, detail in FAKE_KIT_STATE.log.events if name == "call_tool"]
        assert len(calls) == 3  # first attempt + two retries, all on the unreachable server

    def test_fallback_runs_the_fallback_step_which_may_use_another_server(
        self, tmp_path: Path
    ) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = self._unreachable()
        fallback = _step("fallback", server=SECOND, arguments={"text": "fb"})
        strategy = {"type": "fallback", "fallback_step": fallback}
        document = _doc(
            [_step("first", strategy=strategy)],
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED, QUALIFIED2],
        )

        steps = _step_results(_invoke(tmp_path, document, kits=[_kits(tmp_path)]))

        assert steps["first"]["result"] == {"ok": True}
        assert steps["first"]["mcp_server"] == SECOND
        assert sorted(_disconnects(FAKE_KIT_STATE)) == sorted([ENDPOINT, ENDPOINT2])

    def test_the_fallback_step_is_composed_so_an_undeclared_server_stops_the_run(
        self, tmp_path: Path
    ) -> None:
        fallback = _step("fallback", server="ghost_srv")
        document = _doc([_step("first", strategy={"type": "fallback", "fallback_step": fallback})])

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert f"Error [{EXEC_COMPOSITION_FAILED}]" in result.stderr
        assert FAKE_KIT_STATE.log.events == []

    def test_delegate_hands_the_failure_to_the_agent_judged_recovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Provider:
            async def complete(self, **_kwargs: Any) -> dict[str, Any]:
                return {"content": "skip"}

        original = commands_module._build_adapter_registries

        def _with_provider(discovery_result: Any, *, no_kits: bool = False) -> Any:
            agents, _llm, coordination = original(discovery_result, no_kits=no_kits)
            return agents, _Provider(), coordination

        monkeypatch.setattr(commands_module, "_build_adapter_registries", _with_provider)
        FAKE_KIT_STATE.scripts[ENDPOINT] = self._unreachable()
        document = self._two_server_document({"type": "delegate"})

        steps = _step_results(_invoke(tmp_path, document, kits=[_kits(tmp_path)]))

        assert steps["second"]["result"] == {"ok": True}

    def test_delegate_without_a_provider_fails_that_step_only(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = self._unreachable()
        document = self._two_server_document({"type": "delegate"})

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        assert result.exit_code == 1
        assert "BEDDEL-EXEC-010" in result.stderr


class TestRunSchemaValidator:
    """AC 11: the validator is the one from the composition's kit module."""

    _SCHEMA_KIT_INIT = (
        "from beddel_protocol_mcp.http_client import StreamableHTTPMCPClient\n"
        "from _mcp_fakes import FAKE_KIT_STATE, stub_validate_tool_arguments\n"
        "\n"
        "def validate_tool_arguments(arguments, schema):\n"
        "    FAKE_KIT_STATE.validator_calls.append(('from-kit-init', arguments))\n"
        "    stub_validate_tool_arguments(arguments, schema)\n"
    )

    def _kits(self, tmp_path: Path) -> Path:
        return _kits(tmp_path, modules={"__init__.py": self._SCHEMA_KIT_INIT})

    def test_the_validator_of_the_composition_module_is_the_one_called(
        self, tmp_path: Path
    ) -> None:
        document = _doc([_step(arguments={"text": "ok"}, validate_schema=True)])

        steps = _step_results(_invoke(tmp_path, document, kits=[self._kits(tmp_path)]))

        assert steps["call"]["result"] == {"ok": True}
        assert FAKE_KIT_STATE.validator_calls == [("from-kit-init", {"text": "ok"})]
        assert FAKE_KIT_STATE.log.names() == [
            "constructed",
            "connected",
            "list_tools",
            "call_tool",
            "disconnected",
        ]

    def test_violating_arguments_are_rejected_before_the_call(self, tmp_path: Path) -> None:
        document = _doc([_step(arguments={"text": 12345}, validate_schema=True)])

        result = _invoke(tmp_path, document, kits=[self._kits(tmp_path)])

        assert result.exit_code == 1
        assert "BEDDEL-MCP-603" in result.stderr
        assert "call_tool" not in FAKE_KIT_STATE.log.names()
        assert _disconnects(FAKE_KIT_STATE) == [ENDPOINT]

    def test_the_wiring_hands_the_validator_over_without_discovery(self, tmp_path: Path) -> None:
        wiring = MCPWiring()

        _compose(_workflow(), wiring, self._kits(tmp_path))

        module = sys.modules[KIT_MODULE]
        assert wiring.schema_validator is module.validate_tool_arguments

    def test_a_kit_without_a_validator_gives_a_distinct_run_time_error(
        self, tmp_path: Path
    ) -> None:
        kits = _kits(
            tmp_path,
            modules={
                "__init__.py": (
                    "from beddel_protocol_mcp.http_client import StreamableHTTPMCPClient\n"
                )
            },
        )
        document = _doc([_step(arguments={"text": "ok"}, validate_schema=True)])

        result = _invoke(tmp_path, document, kits=[kits])

        assert result.exit_code == 1
        assert "no MCP schema validator was supplied" in result.stderr
        assert "jsonschema" not in result.stderr.lower()
        assert "call_tool" not in FAKE_KIT_STATE.log.names()


# ---------------------------------------------------------------------------
# Run C coverage audit: the same rules proven through the real ``beddel run`` path
# ---------------------------------------------------------------------------


class _ComposeSpy:
    """Records what ``run`` hands to ``compose_mcp`` and what it raises."""

    def __init__(self) -> None:
        self.kit_module_loaded_on_entry: list[bool] = []
        self.errors: list[BaseException] = []

    def reasons(self) -> list[Any]:
        return [getattr(exc, "details", {}).get("reason") for exc in self.errors]


def _spy_compose(monkeypatch: pytest.MonkeyPatch) -> _ComposeSpy:
    spy = _ComposeSpy()
    original = surface.compose_mcp

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        spy.kit_module_loaded_on_entry.append(KIT_MODULE in sys.modules)
        try:
            return original(*args, **kwargs)
        except BaseException as exc:
            spy.errors.append(exc)
            raise

    monkeypatch.setattr(surface, "compose_mcp", _wrapped)
    return spy


def _write_unrelated_kit(kits_dir: Path, name: str) -> None:
    """A minimal kit manifest (no module, no tools) whose name is ``name``."""
    kit_dir = kits_dir / "unrelated-kit"
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yaml").write_text(
        f"name: {name}\nversion: 0.0.0\ndescription: unrelated kit\n"
        "targets:\n  python:\n    status: implemented\n    module: unrelated_kit_pkg\n"
        "    dependencies: []\n"
    )


def _assert_stopped_before_any_step(result: Result) -> None:
    assert result.exit_code == 1
    assert f"Error [{EXEC_COMPOSITION_FAILED}]: {COMPOSITION_FAILED_MESSAGE}" in result.stderr
    assert FAKE_KIT_STATE.log.events == []  # nothing connected, listed or called
    assert FAKE_KIT_STATE.constructor_kwargs == []  # nothing built


class TestRunCompositionRulesThroughTheCli:
    """AC 2, 4, 6, 8: composition rules reached via ``beddel run``, not only ``compose_mcp``."""

    def test_unknown_transport_stops_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _spy_compose(monkeypatch)
        document = _doc(servers={SERVER: _server(transport="mcp-stdio")})

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [REASON_UNKNOWN_TRANSPORT]

    @pytest.mark.parametrize(
        ("server", "tool"),
        [("$input.x", TOOL), (SERVER, "$env.X"), (f"a-$input.{FAKE_SECRET_MARKER}", TOOL)],
        ids=["server-input", "tool-env", "server-embedded"],
    )
    def test_dynamic_names_stop_the_run_without_echo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server: str, tool: str
    ) -> None:
        spy = _spy_compose(monkeypatch)
        document = _doc([_step(server=server, tool=tool)])

        result = _invoke(tmp_path, document, kits=[_kits(tmp_path)])

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [domain_composition.REASON_INVALID_NAME]
        assert FAKE_SECRET_MARKER not in result.output
        assert "$" not in result.output

    def test_a_server_key_equal_to_a_cli_tool_prefix_stops_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``run`` hands the merged tool registry (here a ``--tool`` name) to the composition.
        spy = _spy_compose(monkeypatch)

        result = _invoke(
            tmp_path,
            _doc(),
            kits=[_kits(tmp_path)],
            extra=("--tool", f"{SERVER}:dump=json:dumps"),
        )

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [domain_composition.REASON_NAME_COLLISION]

    def test_a_server_key_equal_to_a_discovered_kit_name_stops_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``run`` hands the names of the discovered kits to the composition.  Kit names
        # are kebab-case and server keys snake_case, so only a one-word name can collide.
        spy = _spy_compose(monkeypatch)
        kits = _kits(tmp_path)
        _write_unrelated_kit(kits, "acme")
        document = _doc([_step(server="acme")], servers={"acme": _server()}, allowed=["acme:echo"])

        result = _invoke(tmp_path, document, kits=[kits])

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [domain_composition.REASON_NAME_COLLISION]

    def test_unrelated_tool_and_kit_names_do_not_collide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _spy_compose(monkeypatch)
        kits = _kits(tmp_path)
        _write_unrelated_kit(kits, "some_other_kit")

        result = _invoke(
            tmp_path,
            _doc([_step(arguments={"text": "hi"})]),
            kits=[kits],
            extra=("--tool", "dump=json:dumps"),
        )

        assert _step_results(result)["call"]["result"] == {"ok": True}
        assert spy.errors == []

    def test_two_kit_locations_stop_the_run_as_ambiguous(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _spy_compose(monkeypatch)
        first = _kits(tmp_path, "kits-a")
        second = _kits(tmp_path, "kits-b")

        result = _invoke(tmp_path, _doc(), kits=[first, second])

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [REASON_KIT_AMBIGUOUS]
        assert KIT_MODULE not in sys.modules

    def test_a_module_preloaded_from_another_directory_stops_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _spy_compose(monkeypatch)
        decoy_source = write_fake_kit(tmp_path / "decoy-kits")
        sys.path.insert(0, str(decoy_source))
        decoy = importlib.import_module(KIT_MODULE)
        executions = list(FAKE_KIT_STATE.module_executions)

        result = _invoke(tmp_path, _doc(), kits=[_kits(tmp_path)])

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [REASON_KIT_LOCATION_MISMATCH]
        assert sys.modules[KIT_MODULE] is decoy  # never deleted, replaced or reloaded
        assert FAKE_KIT_STATE.module_executions == executions

    def test_the_real_loader_preloads_the_kit_and_the_composition_accepts_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No stubbing of the loader path here: ``_ensure_kit_paths`` puts the configured
        # kit directory on ``sys.path`` and ``load_kit_adapters`` imports the module
        # (then fails to build a zero-argument adapter and skips it, D-5, pre-existing)
        # before the composition runs.  The composition must accept that module.
        kits = _kits(tmp_path)
        (tmp_path / ".beddel.json").write_text(json.dumps({"kits_paths": [str(kits)]}))
        monkeypatch.setattr(commands_module, "_ensure_kit_paths", _REAL_ENSURE_KIT_PATHS)
        spy = _spy_compose(monkeypatch)
        document = _doc([_step(arguments={"text": "hi"})])

        steps = _step_results(_invoke(tmp_path, document))  # no --kit: only the configuration

        assert steps["call"]["result"] == {"ok": True}
        assert spy.kit_module_loaded_on_entry == [True]  # preloaded by the loader path
        assert spy.errors == []
        assert len(FAKE_KIT_STATE.module_executions) == 1  # executed once, not reloaded
        assert FAKE_KIT_STATE.log.names() == [
            "constructed",
            "connected",
            "call_tool",
            "disconnected",
        ]


class TestRunNestedStepsThroughTheCli:
    """AC 2 and 14: a nested step at depth is composed, built, connected on use, closed."""

    @staticmethod
    def _carrier(step_id: str, **extra: Any) -> dict[str, Any]:
        # A step whose condition is false (no input), so only its ``else`` branch runs.
        return {
            "id": step_id,
            "primitive": "tool",
            "if": "$input.go == 'yes'",
            "config": {"tool": "unused"},
            **extra,
        }

    def test_a_step_three_levels_deep_with_a_nested_fallback_runs(self, tmp_path: Path) -> None:
        FAKE_KIT_STATE.scripts[ENDPOINT] = ClientScript(
            call_error=MCPError(MCP_CONNECTION_FAILED, "Unreachable MCP server")
        )
        rescue = _step("rescue", server=SECOND, arguments={"text": "fb"})
        leaf = _step("leaf", strategy={"type": "fallback", "fallback_step": rescue})
        chain = self._carrier("l1", **{"else": [self._carrier("l2", **{"else": [leaf]})]})
        document = _doc(
            [chain],
            servers={SERVER: _server(), SECOND: _server(endpoint=ENDPOINT2)},
            allowed=[QUALIFIED, QUALIFIED2],
        )

        steps = _step_results(_invoke(tmp_path, document, kits=[_kits(tmp_path)]))

        assert steps["leaf"]["mcp_server"] == SECOND  # the fallback (depth 4) ran
        built = [d for n, d in FAKE_KIT_STATE.log.events if n == "constructed"]
        assert built == [ENDPOINT, ENDPOINT2]  # both composed before the first step
        connected = [d for n, d in FAKE_KIT_STATE.log.events if n == "connected"]
        assert sorted(connected) == sorted([ENDPOINT, ENDPOINT2])
        assert sorted(_disconnects(FAKE_KIT_STATE)) == sorted([ENDPOINT, ENDPOINT2])

    def test_an_undeclared_server_at_depth_three_stops_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = _spy_compose(monkeypatch)
        leaf = _step("leaf", server="ghost_srv")
        chain = self._carrier("l1", **{"else": [self._carrier("l2", **{"then": [leaf]})]})

        result = _invoke(tmp_path, _doc([chain]), kits=[_kits(tmp_path)])

        _assert_stopped_before_any_step(result)
        assert spy.reasons() == [domain_composition.REASON_UNDECLARED_SERVER]


def _scenario_missing_allowlist(tmp_path: Path) -> ExecutionError:
    document = _doc()
    del document["allowed_tools"]
    return _composition_error(_workflow(document), _kits(tmp_path))


def _scenario_invalid_name(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(_doc([_step(server="$input.x")])), _kits(tmp_path))


def _scenario_undeclared_server(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(_doc([_step(server="ghost_srv")])), _kits(tmp_path))


def _scenario_unknown_transport(tmp_path: Path) -> ExecutionError:
    document = _doc(servers={SERVER: _server(transport="mcp-stdio")})
    return _composition_error(_workflow(document), _kits(tmp_path))


def _scenario_tool_not_allowed(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(_doc(allowed=[])), _kits(tmp_path))


def _scenario_name_collision(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(), _kits(tmp_path), kit_names=(SERVER,))


def _scenario_kits_disabled(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(), _kits(tmp_path), no_kits=True)


def _scenario_kit_unavailable(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(), None)


def _scenario_kit_ambiguous(tmp_path: Path) -> ExecutionError:
    return _composition_error(_workflow(), [_kits(tmp_path, "kits-a"), _kits(tmp_path, "kits-b")])


def _scenario_kit_location_mismatch(tmp_path: Path) -> ExecutionError:
    sys.path.insert(0, str(write_fake_kit(tmp_path / "decoy-kits")))
    importlib.import_module(KIT_MODULE)
    return _composition_error(_workflow(), _kits(tmp_path))


def _scenario_adapter_unavailable(tmp_path: Path) -> ExecutionError:
    kits = _kits(tmp_path, modules={"__init__.py": "def validate_tool_arguments(a, s): ..."})
    return _composition_error(_workflow(), kits)


def _scenario_adapter_construction_failed(tmp_path: Path) -> ExecutionError:
    FAKE_KIT_STATE.constructor_errors[ENDPOINT] = RuntimeError("boom")
    return _composition_error(_workflow(), _kits(tmp_path))


_REASON_SCENARIOS = {
    domain_composition.REASON_MISSING_ALLOWLIST: _scenario_missing_allowlist,
    domain_composition.REASON_INVALID_NAME: _scenario_invalid_name,
    domain_composition.REASON_UNDECLARED_SERVER: _scenario_undeclared_server,
    REASON_UNKNOWN_TRANSPORT: _scenario_unknown_transport,
    domain_composition.REASON_TOOL_NOT_ALLOWED: _scenario_tool_not_allowed,
    domain_composition.REASON_NAME_COLLISION: _scenario_name_collision,
    REASON_KITS_DISABLED: _scenario_kits_disabled,
    REASON_KIT_UNAVAILABLE: _scenario_kit_unavailable,
    REASON_KIT_AMBIGUOUS: _scenario_kit_ambiguous,
    REASON_KIT_LOCATION_MISMATCH: _scenario_kit_location_mismatch,
    REASON_ADAPTER_UNAVAILABLE: _scenario_adapter_unavailable,
    REASON_ADAPTER_CONSTRUCTION_FAILED: _scenario_adapter_construction_failed,
}


class TestEveryCompositionReasonIsReachable:
    """AC 12: every ``details["reason"]`` value is reachable, with one code and one message."""

    @pytest.mark.parametrize("reason", sorted(_REASON_SCENARIOS))
    def test_the_scenario_produces_its_reason(self, tmp_path: Path, reason: str) -> None:
        err = _REASON_SCENARIOS[reason](tmp_path)

        assert err.details["reason"] == reason
        assert err.code == EXEC_COMPOSITION_FAILED
        assert err.message == COMPOSITION_FAILED_MESSAGE
        assert FAKE_KIT_STATE.log.events == []  # no I/O whatever the reason

    def test_no_reason_constant_is_left_without_a_scenario(self) -> None:
        declared = {
            getattr(domain_composition, name)
            for name in dir(domain_composition)
            if name.startswith("REASON_")
        }

        assert set(_REASON_SCENARIOS) == declared
        assert len(declared) == 12
