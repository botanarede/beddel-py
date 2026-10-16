"""The Story 1.2b MCP suites run with no network, no MCP SDK and no credential (AC 16).

The three suites below use a fake client adapter and a fake kit written under a
temporary directory.  This module proves the claim instead of asserting it: it
runs the suites in a child pytest process whose plugin

* refuses every import of the MCP SDK and of the common HTTP client libraries,
* refuses every outbound socket operation and name resolution, and records the
  attempt (a suite that swallowed the error would still be reported),
* and runs with a scrubbed environment (no credential variable, an empty home).

The child exits non-zero when any test fails, when a refused import was
attempted, or when a socket operation was attempted.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# The suites written for Story 1.2b.  This module is not part of the list.
HERMETIC_SUITES = (
    "tests/domain/test_mcp_composition.py",
    "tests/primitives/test_tool_mcp_enforcement.py",
    "tests/cli/test_run_mcp_composition.py",
)

# The three suites hold well over this many tests; an accidental empty
# collection must not pass as a hermetic run.
MINIMUM_PASSED = 150

_PLUGIN = '''\
"""Pytest plugin: no MCP SDK, no HTTP client library, no outbound socket."""
import importlib.abc
import socket
import sys

BLOCKED_ROOTS = ("mcp", "httpx", "httpx_sse", "httpcore", "requests", "urllib3", "aiohttp")
attempts = []


class _RefuseImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        root = fullname.partition(".")[0]
        if root in BLOCKED_ROOTS:
            attempts.append("import:" + root)
            raise ImportError("refused by the hermetic run: " + root)
        return None


def _refuse(name):
    def _blocked(*args, **kwargs):
        attempts.append("socket:" + name)
        raise AssertionError("network access attempted: " + name)

    return _blocked


sys.meta_path.insert(0, _RefuseImports())
for _name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection"):
    setattr(socket, _name, _refuse(_name))
for _name in ("connect", "connect_ex", "sendto"):
    setattr(socket.socket, _name, _refuse(_name))


def pytest_sessionfinish(session, exitstatus):
    imported = [root for root in BLOCKED_ROOTS if root in sys.modules]
    print("HERMETIC attempts=%d imported=%s" % (len(attempts), imported))
    if attempts or imported:
        session.exitstatus = 1
'''


def _scrubbed_environment(home: Path, plugin_dir: Path) -> dict[str, str]:
    """A child environment with the interpreter basics and nothing else."""
    import beddel

    src = Path(beddel.__file__).resolve().parents[1]
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PYTHONPATH": os.pathsep.join([str(plugin_dir), str(src)]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def test_the_mcp_suites_run_without_network_sdk_or_credential(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "hermetic_plugin.py").write_text(textwrap.dedent(_PLUGIN))
    home = tmp_path / "home"
    home.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "hermetic_plugin",
            "-p",
            "no:cacheprovider",
            "-q",
            "--no-header",
            *HERMETIC_SUITES,
        ],
        cwd=PACKAGE_ROOT,
        env=_scrubbed_environment(home, plugin_dir),
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output[-4000:]
    assert "HERMETIC attempts=0 imported=[]" in output
    summary = re.search(r"(\d+) passed", output)
    assert summary is not None, output[-2000:]
    assert int(summary.group(1)) >= MINIMUM_PASSED
    assert " failed" not in output
    assert " skipped" not in output
    assert list(home.iterdir()) == []  # nothing was written to the (empty) home
