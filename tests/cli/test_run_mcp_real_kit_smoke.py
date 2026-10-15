"""Smoke test: compose against the REAL ``protocol-mcp-kit`` directory (Story 1.2b, Run C).

Every other composition test uses a fake kit.  This one points the composition
at the kit directory that ships in the repository (read only) and proves, with
the real adapter class and the real validator:

* the composition imports the kit from the one location it was given (not from
  ``sys.path``: the child interpreter does not have the kit on its path),
* constructing ``StreamableHTTPMCPClient`` performs no I/O (every socket
  operation and name resolution is refused, and the credential store, here an
  empty home directory, is left untouched),
* the schema validator handed to the tool primitive is the function of that
  same kit module object.

No network and no credential are used, and no connection is attempted
(``authorization: none``, an unroutable ``.invalid`` endpoint, and the child
refuses sockets).  The check runs in a child interpreter so that neither the
kit nor the MCP SDK is ever imported into the pytest process.  It is skipped
cleanly when the kit directory cannot be found or when the kit's own imports
(the SDK) are unavailable in the environment.

Where the kit is looked for (no configuration key and no environment variable
is introduced): a directory of ``sys.path`` that holds ``beddel_protocol_mcp``
inside a ``protocol-mcp-kit/{python,src}`` layout, then the monorepo layout
``<repo>/vendor/beddel/kits/protocol-mcp-kit``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

KIT_DIRECTORY_NAME = "protocol-mcp-kit"
KIT_PACKAGE = "beddel_protocol_mcp"
SERVER = "remote_srv"
TOOL = "echo"
ENDPOINT = "https://mcp.example.invalid/mcp"

_CHILD = textwrap.dedent(
    """\
    import json
    import socket
    import sys
    from pathlib import Path

    kits_root, home = Path(sys.argv[1]), Path(sys.argv[2])
    attempts = []


    def _refuse(name):
        def _blocked(*args, **kwargs):
            attempts.append(name)
            raise AssertionError("network access attempted: " + name)

        return _blocked


    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection"):
        setattr(socket, name, _refuse(name))
    for name in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, name, _refuse(name))

    from beddel.cli.mcp_composition import KIT_MODULE, MCPWiring, compose_mcp
    from beddel.domain.errors import BeddelError
    from beddel.domain.models import Workflow

    workflow = Workflow.model_validate(
        {
            "id": "wf",
            "name": "wf",
            "steps": [
                {
                    "id": "call",
                    "primitive": "tool",
                    "config": {"mcp_server": "%(server)s", "tool": "%(tool)s"},
                }
            ],
            "mcp_servers": {
                "%(server)s": {
                    "transport": "mcp-streamable-http",
                    "endpoint": "%(endpoint)s",
                    "authorization": "none",
                }
            },
            "allowed_tools": ["%(server)s:%(tool)s"],
        }
    )
    wiring = MCPWiring()
    try:
        compose_mcp(
            workflow,
            wiring,
            kit_paths=[kits_root],
            no_kits=False,
            tool_names=(),
            kit_names=(),
        )
    except BeddelError as exc:
        print(
            json.dumps(
                {
                    "status": "composition-error",
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            )
        )
        sys.exit(3)

    module = sys.modules[KIT_MODULE]
    client = (wiring.registry or {})["%(server)s"]
    validator = wiring.schema_validator
    code = None
    try:
        validator({"text": 1}, {"type": "object", "properties": {"text": {"type": "string"}}})
    except BeddelError as exc:
        code = exc.code
    print(
        json.dumps(
            {
                "status": "ok",
                "module_file": str(Path(module.__file__).resolve()),
                "client_class_is_kit_class": type(client) is module.StreamableHTTPMCPClient,
                "client_module": type(client).__module__,
                "validator_is_kit_function": validator is module.validate_tool_arguments,
                "validator_module": getattr(validator, "__module__", None),
                "kit_modules_loaded": sorted(
                    n for n in sys.modules if n == KIT_MODULE or n.startswith(KIT_MODULE + ".")
                ),
                "registry_keys": list(wiring.registry or {}),
                "socket_attempts": attempts,
                "home_entries": sorted(p.name for p in home.iterdir()),
                "violation_code": code,
            }
        )
    )
    """
) % {"server": SERVER, "tool": TOOL, "endpoint": ENDPOINT}


def _real_kit_directory() -> Path | None:
    """The real ``protocol-mcp-kit`` directory, or ``None`` when it cannot be found."""
    for entry in sys.path:
        source = Path(entry or ".")
        if (
            source.name in {"python", "src"}
            and source.parent.name == KIT_DIRECTORY_NAME
            and (source / KIT_PACKAGE / "__init__.py").is_file()
            and (source.parent / "kit.yaml").is_file()
        ):
            return source.parent.resolve()
    monorepo = Path(__file__).resolve().parents[4] / "vendor" / "beddel" / "kits"
    candidate = monorepo / KIT_DIRECTORY_NAME
    if (candidate / "kit.yaml").is_file():
        return candidate.resolve()
    return None


def _kit_dependencies_are_missing(facts: dict[str, object]) -> bool:
    """Whether the child failed only because the kit's own SDK is not installed.

    Either the kit package could not be imported (``kit_unavailable``) or the kit
    constructed nothing because its guarded SDK import failed: the kit then raises
    its own ``BEDDEL-MCP-600`` with the fixed sentence "MCP SDK not installed".
    """
    details = facts.get("details")
    if isinstance(details, dict) and details.get("reason") == "kit_unavailable":
        return True
    message = facts.get("message")
    return (
        facts.get("code") == "BEDDEL-MCP-600"
        and isinstance(message, str)
        and "SDK not installed" in message
    )


def _kit_source(kit_dir: Path) -> Path:
    python = kit_dir / "python"
    return python if python.is_dir() else kit_dir / "src"


def _child_environment(home: Path) -> dict[str, str]:
    """Interpreter basics and ``beddel`` on the path; the kit is deliberately not."""
    import beddel

    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PYTHONPATH": str(Path(beddel.__file__).resolve().parents[1]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def test_composition_against_the_real_kit_constructs_without_io(tmp_path: Path) -> None:
    kit_dir = _real_kit_directory()
    if kit_dir is None:
        pytest.skip(
            "the real protocol-mcp-kit directory was not found "
            "(put its python/ directory on PYTHONPATH, or run inside the monorepo)"
        )
    home = tmp_path / "home"
    home.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()  # no ./kits convenience directory here

    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, str(kit_dir.parent), str(home)],
        cwd=workdir,
        env=_child_environment(home),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, completed.stdout[-2000:] + completed.stderr[-2000:]
    facts = json.loads(lines[-1])
    if facts["status"] == "composition-error" and _kit_dependencies_are_missing(facts):
        pytest.skip(
            "the real kit's own dependencies are unavailable in this environment "
            f"({facts['details'].get('error_type') or facts['message']})"
        )
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    assert facts["status"] == "ok", facts

    # One import location: the module is the one under the kit directory we named.
    assert Path(facts["module_file"]).is_relative_to(_kit_source(kit_dir).resolve())
    assert facts["kit_modules_loaded"][0] == KIT_PACKAGE
    # The adapter and the validator come from that single module object.
    assert facts["registry_keys"] == [SERVER]
    assert facts["client_class_is_kit_class"] is True
    assert facts["client_module"].startswith(f"{KIT_PACKAGE}.")
    assert facts["validator_is_kit_function"] is True
    assert facts["validator_module"] == f"{KIT_PACKAGE}.schema_validator"
    # The real validator rejects a violating argument with the registered code.
    assert facts["violation_code"] == "BEDDEL-MCP-603"
    # Construction performed no I/O: no socket operation, nothing written to the home.
    assert facts["socket_attempts"] == []
    assert facts["home_entries"] == []
