"""Integration tests for Agent Engine sidebar wiring in _build_runtime_app().

Verifies that when vertexai is available + ADC is configured, _build_runtime_app()
registers the Agent Engine sidebar routes on the returned FastAPI app, and that
when vertexai is absent the routes are simply omitted (graceful degradation).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import APIRouter

from beddel.flows import get_bundled_workflow_path


@pytest.fixture(autouse=True)
def _stub_kit_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep wiring tests independent of the developer's local kit paths."""
    import beddel.cli.commands as commands

    monkeypatch.setattr(commands, "_ensure_kit_paths", lambda *_a, **_kw: None)
    monkeypatch.setattr(commands, "_validate_config_paths", lambda *_a, **_kw: None)

    fake_serve_fastapi = types.ModuleType("beddel_serve_fastapi")
    fake_serve_fastapi.__path__ = []
    fake_handler = types.ModuleType("beddel_serve_fastapi.handler")
    fake_handler.create_beddel_handler = lambda *_a, **_kw: APIRouter()
    fake_serve_fastapi.handler = fake_handler
    monkeypatch.setitem(sys.modules, "beddel_serve_fastapi", fake_serve_fastapi)
    monkeypatch.setitem(sys.modules, "beddel_serve_fastapi.handler", fake_handler)


@pytest.fixture()
def setup_wf() -> tuple[Path, ...]:
    """Return the bundled setup workflow as a single-item tuple of paths."""
    return (get_bundled_workflow_path("setup"),)


def _route_paths(app: object) -> list[str]:
    """Extract all route path strings from a FastAPI app."""
    return [p for r in getattr(app, "routes", []) if (p := getattr(r, "path", None)) is not None]


class TestAgentEngineSidebarWiring:
    """Verify _build_runtime_app wires Agent Engine routes when vertexai available."""

    def test_registers_sidebar_routes_when_available(self, setup_wf: tuple[Path, ...]) -> None:
        """When _AE_AVAILABLE=True + ADC configured, sidebar endpoints appear on app."""
        mock_adapter_instance = MagicMock()

        with (
            patch(
                "beddel.serve.agent_engine.adapter._AVAILABLE",
                True,
            ),
            patch(
                "beddel.serve.agent_engine.VertexAgentEngineAdapter.__init__",
                return_value=None,
            ),
            patch(
                "beddel.serve.agent_engine.VertexAgentEngineAdapter",
                return_value=mock_adapter_instance,
            ),
        ):
            from beddel.cli.commands import _build_runtime_app

            app, _loaded, _ids = _build_runtime_app(setup_wf, no_kits=True)

        paths = _route_paths(app)
        assert "/api/agent-engine/agents" in paths
        assert "/api/agent-engine/sidebar" in paths

    def test_no_sidebar_routes_when_unavailable(self, setup_wf: tuple[Path, ...]) -> None:
        """When _AE_AVAILABLE=False, sidebar endpoints are absent — no exception raised."""
        with patch(
            "beddel.serve.agent_engine.adapter._AVAILABLE",
            False,
        ):
            from beddel.cli.commands import _build_runtime_app

            app, _loaded, _ids = _build_runtime_app(setup_wf, no_kits=True)

        paths = _route_paths(app)
        assert "/api/agent-engine/agents" not in paths
        assert "/api/agent-engine/sidebar" not in paths
