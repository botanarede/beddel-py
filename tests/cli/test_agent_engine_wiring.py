"""Integration tests for Agent Engine sidebar wiring in _build_runtime_app().

Verifies that when vertexai is available + ADC is configured, _build_runtime_app()
registers the Agent Engine sidebar routes on the returned FastAPI app, and that
when vertexai is absent the routes are simply omitted (graceful degradation).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from beddel.flows import get_bundled_workflow_path


@pytest.fixture()
def setup_wf() -> tuple[Path, ...]:
    """Return the bundled setup workflow as a single-item tuple of paths."""
    return (get_bundled_workflow_path("setup"),)


def _route_paths(app: object) -> list[str]:
    """Extract all route path strings from a FastAPI app."""
    return [r.path for r in getattr(app, "routes", [])]  # type: ignore[attr-defined]


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
