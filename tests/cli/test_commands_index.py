"""Integration tests for IndexStore in _build_runtime_app().

Tests AC#4 (sync called), AC#5 (kit filtering), AC#6 (flow filtering),
AC#8 (graceful degradation).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


class TestBuildRuntimeAppIndexSync:
    """AC#4: _build_runtime_app calls sync_kits and sync_flows after discovery."""

    def test_index_store_sync_kits_called(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """IndexStore.sync_kits is called with discovered manifests."""
        sync_kits_called: list[Any] = []
        sync_flows_called: list[Any] = []

        class FakeIndexStore:
            def __init__(self, db_path: str | Path = "") -> None:
                pass

            async def sync_kits(self, manifests: list[Any]) -> None:
                sync_kits_called.append(manifests)

            async def sync_flows(self, workflows: list[Any]) -> None:
                sync_flows_called.append(workflows)

            async def list_kits(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
                return [{"name": "test-kit"}] if enabled_only else []

            async def list_flows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
                return []

        monkeypatch.setattr("beddel.adapters.index_store.IndexStore", FakeIndexStore)

        # Create a minimal workflow file
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(
            "name: test-flow\nid: test-flow-1\ndescription: test\nsteps:\n"
            "  - id: s1\n    primitive: output\n    config:\n      template: hello\n"
        )

        # Mock heavy dependencies
        mock_app = MagicMock()
        mock_app.add_middleware = MagicMock()
        mock_app.include_router = MagicMock()
        mock_app.get = MagicMock(return_value=lambda f: f)

        monkeypatch.setattr("beddel.cli.commands._ensure_kit_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._validate_config_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_flow_paths", lambda _: (wf_file,))

        # Mock discover_kits to return empty result
        from beddel.domain.kit import KitDiscoveryResult

        empty_result = KitDiscoveryResult(manifests=[], collisions=[])
        monkeypatch.setattr("beddel.tools.kits.discover_kits", lambda _paths: empty_result)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_kit_paths", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_adapter_registries",
            lambda _dr, **_kw: ({}, MagicMock()),
        )
        monkeypatch.setattr("beddel.cli.commands._parse_tool_flags", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_tool_registry",
            lambda *_a, **_kw: MagicMock(),
        )

        # Mock FastAPI and handler
        monkeypatch.setattr("fastapi.FastAPI", lambda **_kw: mock_app)
        monkeypatch.setattr(
            "beddel_serve_fastapi.handler.create_beddel_handler",
            lambda *_a, **_kw: MagicMock(),
        )

        from beddel.cli.commands import _build_runtime_app

        _build_runtime_app((wf_file,))

        assert len(sync_kits_called) == 1
        assert len(sync_flows_called) == 1


class TestBuildRuntimeAppGracefulDegradation:
    """AC#8: If index.db is corrupt/unavailable, log warning and continue."""

    def test_oserror_on_init_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """OSError during IndexStore init logs warning, doesn't crash."""

        class FailingIndexStore:
            def __init__(self, db_path: str | Path = "") -> None:
                raise OSError("Permission denied")

        monkeypatch.setattr("beddel.adapters.index_store.IndexStore", FailingIndexStore)

        # Create a minimal workflow file
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(
            "name: test-flow\nid: test-flow-1\ndescription: test\nsteps:\n"
            "  - id: s1\n    primitive: output\n    config:\n      template: hello\n"
        )

        mock_app = MagicMock()
        mock_app.add_middleware = MagicMock()
        mock_app.include_router = MagicMock()
        mock_app.get = MagicMock(return_value=lambda f: f)

        monkeypatch.setattr("beddel.cli.commands._ensure_kit_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._validate_config_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_flow_paths", lambda _: (wf_file,))

        from beddel.domain.kit import KitDiscoveryResult

        empty_result = KitDiscoveryResult(manifests=[], collisions=[])
        monkeypatch.setattr("beddel.tools.kits.discover_kits", lambda _paths: empty_result)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_kit_paths", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_adapter_registries",
            lambda _dr, **_kw: ({}, MagicMock()),
        )
        monkeypatch.setattr("beddel.cli.commands._parse_tool_flags", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_tool_registry",
            lambda *_a, **_kw: MagicMock(),
        )
        monkeypatch.setattr("fastapi.FastAPI", lambda **_kw: mock_app)
        monkeypatch.setattr(
            "beddel_serve_fastapi.handler.create_beddel_handler",
            lambda *_a, **_kw: MagicMock(),
        )

        from beddel.cli.commands import _build_runtime_app

        # Should not raise — graceful degradation
        app, loaded, wf_ids = _build_runtime_app((wf_file,))
        assert loaded == 1
        assert "test-flow-1" in wf_ids

    def test_database_error_on_sync_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """sqlite3.DatabaseError during sync_kits logs warning, doesn't crash."""

        class CorruptIndexStore:
            def __init__(self, db_path: str | Path = "") -> None:
                pass

            async def sync_kits(self, manifests: list[Any]) -> None:
                raise sqlite3.DatabaseError("database disk image is malformed")

        monkeypatch.setattr("beddel.adapters.index_store.IndexStore", CorruptIndexStore)

        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(
            "name: test-flow\nid: test-flow-1\ndescription: test\nsteps:\n"
            "  - id: s1\n    primitive: output\n    config:\n      template: hello\n"
        )

        mock_app = MagicMock()
        mock_app.add_middleware = MagicMock()
        mock_app.include_router = MagicMock()
        mock_app.get = MagicMock(return_value=lambda f: f)

        monkeypatch.setattr("beddel.cli.commands._ensure_kit_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._validate_config_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_flow_paths", lambda _: (wf_file,))

        from beddel.domain.kit import KitDiscoveryResult

        empty_result = KitDiscoveryResult(manifests=[], collisions=[])
        monkeypatch.setattr("beddel.tools.kits.discover_kits", lambda _paths: empty_result)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_kit_paths", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_adapter_registries",
            lambda _dr, **_kw: ({}, MagicMock()),
        )
        monkeypatch.setattr("beddel.cli.commands._parse_tool_flags", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_tool_registry",
            lambda *_a, **_kw: MagicMock(),
        )
        monkeypatch.setattr("fastapi.FastAPI", lambda **_kw: mock_app)
        monkeypatch.setattr(
            "beddel_serve_fastapi.handler.create_beddel_handler",
            lambda *_a, **_kw: MagicMock(),
        )

        from beddel.cli.commands import _build_runtime_app

        # Should not raise — graceful degradation
        app, loaded, wf_ids = _build_runtime_app((wf_file,))
        assert loaded == 1


class TestBuildRuntimeAppKitFiltering:
    """AC#5: Disabled kits are excluded from tool registry."""

    def test_disabled_kit_excluded_from_discovery_result(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Kits not in enabled list are filtered out before _build_tool_registry."""
        captured_discovery_results: list[Any] = []

        class FilteringIndexStore:
            def __init__(self, db_path: str | Path = "") -> None:
                pass

            async def sync_kits(self, manifests: list[Any]) -> None:
                pass

            async def sync_flows(self, workflows: list[Any]) -> None:
                pass

            async def list_kits(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
                if enabled_only:
                    # Only kit-a is enabled, kit-b is disabled
                    return [{"name": "kit-a"}]
                return [{"name": "kit-a"}, {"name": "kit-b"}]

            async def list_flows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
                return [{"id": "test-flow-1"}]

        monkeypatch.setattr("beddel.adapters.index_store.IndexStore", FilteringIndexStore)

        # Create mock manifests for two kits
        from beddel.domain.kit import KitDiscoveryResult

        mock_kit_a = MagicMock()
        mock_kit_a.kit.name = "kit-a"
        mock_kit_a.kit.tools = []
        mock_kit_a.kit.adapters = []

        mock_kit_b = MagicMock()
        mock_kit_b.kit.name = "kit-b"
        mock_kit_b.kit.tools = []
        mock_kit_b.kit.adapters = []

        two_kit_result = KitDiscoveryResult(manifests=[mock_kit_a, mock_kit_b], collisions=[])

        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(
            "name: test-flow\nid: test-flow-1\ndescription: test\nsteps:\n"
            "  - id: s1\n    primitive: output\n    config:\n      template: hello\n"
        )

        mock_app = MagicMock()
        mock_app.add_middleware = MagicMock()
        mock_app.include_router = MagicMock()
        mock_app.get = MagicMock(return_value=lambda f: f)

        monkeypatch.setattr("beddel.cli.commands._ensure_kit_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._validate_config_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_flow_paths", lambda _: (wf_file,))
        monkeypatch.setattr("beddel.tools.kits.discover_kits", lambda _paths: two_kit_result)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_kit_paths", lambda _: [])

        def _capture_adapter_registries(dr: Any, **_kw: Any) -> tuple[dict, MagicMock]:
            captured_discovery_results.append(dr)
            return ({}, MagicMock())

        monkeypatch.setattr(
            "beddel.cli.commands._build_adapter_registries",
            _capture_adapter_registries,
        )
        monkeypatch.setattr("beddel.cli.commands._parse_tool_flags", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_tool_registry",
            lambda *_a, **_kw: MagicMock(),
        )
        monkeypatch.setattr("fastapi.FastAPI", lambda **_kw: mock_app)
        monkeypatch.setattr(
            "beddel_serve_fastapi.handler.create_beddel_handler",
            lambda *_a, **_kw: MagicMock(),
        )

        from beddel.cli.commands import _build_runtime_app

        _build_runtime_app((wf_file,))

        # _build_adapter_registries should receive filtered result (only kit-a)
        assert len(captured_discovery_results) == 1
        filtered_result = captured_discovery_results[0]
        manifest_names = [m.kit.name for m in filtered_result.manifests]
        assert "kit-a" in manifest_names
        assert "kit-b" not in manifest_names


class TestBuildRuntimeAppFlowFiltering:
    """AC#6: Disabled flows are excluded from mounting."""

    def test_disabled_flow_not_mounted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Flows not in enabled list are not mounted as endpoints."""

        class FlowFilteringIndexStore:
            def __init__(self, db_path: str | Path = "") -> None:
                pass

            async def sync_kits(self, manifests: list[Any]) -> None:
                pass

            async def sync_flows(self, workflows: list[Any]) -> None:
                pass

            async def list_kits(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
                return []

            async def list_flows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
                if enabled_only:
                    # Only flow-1 is enabled, flow-2 is disabled
                    return [{"id": "flow-1"}]
                return [{"id": "flow-1"}, {"id": "flow-2"}]

        monkeypatch.setattr("beddel.adapters.index_store.IndexStore", FlowFilteringIndexStore)

        # Create two workflow files
        wf1 = tmp_path / "flow1.yaml"
        wf1.write_text(
            "name: Flow One\nid: flow-1\ndescription: first\nsteps:\n"
            "  - id: s1\n    primitive: output\n    config:\n      template: hello\n"
        )
        wf2 = tmp_path / "flow2.yaml"
        wf2.write_text(
            "name: Flow Two\nid: flow-2\ndescription: second\nsteps:\n"
            "  - id: s1\n    primitive: output\n    config:\n      template: world\n"
        )

        mock_app = MagicMock()
        mock_app.add_middleware = MagicMock()
        mock_app.include_router = MagicMock()
        mock_app.get = MagicMock(return_value=lambda f: f)

        from beddel.domain.kit import KitDiscoveryResult

        empty_result = KitDiscoveryResult(manifests=[], collisions=[])

        monkeypatch.setattr("beddel.cli.commands._ensure_kit_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._validate_config_paths", lambda: None)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_flow_paths", lambda _: (wf1, wf2))
        monkeypatch.setattr("beddel.tools.kits.discover_kits", lambda _paths: empty_result)
        monkeypatch.setattr("beddel.cli.commands._resolve_all_kit_paths", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_adapter_registries",
            lambda _dr, **_kw: ({}, MagicMock()),
        )
        monkeypatch.setattr("beddel.cli.commands._parse_tool_flags", lambda _: [])
        monkeypatch.setattr(
            "beddel.cli.commands._build_tool_registry",
            lambda *_a, **_kw: MagicMock(),
        )
        monkeypatch.setattr("fastapi.FastAPI", lambda **_kw: mock_app)
        monkeypatch.setattr(
            "beddel_serve_fastapi.handler.create_beddel_handler",
            lambda *_a, **_kw: MagicMock(),
        )

        from beddel.cli.commands import _build_runtime_app

        app, loaded, wf_ids = _build_runtime_app((wf1, wf2))

        # Only flow-1 should be mounted (flow-2 is disabled)
        assert loaded == 1
        assert "flow-1" in wf_ids
        assert "flow-2" not in wf_ids
