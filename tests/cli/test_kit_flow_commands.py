"""Unit tests for index-backed ``beddel kit list`` CLI command.

Tests the refactored kit_list that reads from IndexStore instead of
filesystem discovery.  Uses click.testing.CliRunner with a temporary
SQLite index.db populated via IndexStore.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from beddel.adapters.index_store import IndexStore
from beddel.cli.commands import cli

_INDEX_STORE_DB_PATH = "beddel.adapters.index_store._DEFAULT_DB_PATH"


def _populate_kits(db_path: Path, kits: list[dict[str, object]]) -> None:
    """Insert kit rows into a temporary index.db via IndexStore."""
    store = IndexStore(db_path)
    asyncio.run(store._ensure_initialized())

    conn = sqlite3.connect(str(db_path))
    now = "2026-01-01T00:00:00+00:00"
    with conn:
        for k in kits:
            conn.execute(
                "INSERT INTO kit_index "
                "(name, version, description, category, path, enabled, port, "
                "discovered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    k.get("name", "test-kit"),
                    k.get("version", "0.1.0"),
                    k.get("description", ""),
                    k.get("category", "general"),
                    k.get("path", "/tmp/kits/test"),
                    k.get("enabled", 1),
                    k.get("port", ""),
                    now,
                    now,
                ),
            )
    conn.close()


# ---------------------------------------------------------------------------
# beddel kit list — tabular output
# ---------------------------------------------------------------------------


class TestKitListTabular:
    """Tests for ``beddel kit list`` tabular output from IndexStore."""

    def test_kit_list_populated_index(self, tmp_path: Path) -> None:
        """Populated index shows tabular output with correct columns."""
        db_path = tmp_path / "index.db"
        _populate_kits(
            db_path,
            [
                {
                    "name": "provider-litellm-kit",
                    "version": "1.0.0",
                    "category": "llm",
                    "port": "llm",
                    "enabled": 1,
                },
                {
                    "name": "tools-deploy-kit",
                    "version": "0.2.0",
                    "category": "devops",
                    "port": "tool",
                    "enabled": 0,
                },
            ],
        )

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "NAME" in result.output
        assert "VERSION" in result.output
        assert "ENABLED" in result.output
        assert "CATEGORY" in result.output
        assert "PORT" in result.output
        assert "provider-litellm-kit" in result.output
        assert "1.0.0" in result.output
        assert "\u2713" in result.output  # enabled
        assert "\u2717" in result.output  # disabled
        assert "tools-deploy-kit" in result.output

    def test_kit_list_empty_index(self, tmp_path: Path) -> None:
        """Empty index (no kits) prints 'No kits found.'."""
        db_path = tmp_path / "index.db"
        # Create the db with schema but no rows
        store = IndexStore(db_path)
        asyncio.run(store._ensure_initialized())

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "No kits found" in result.output


# ---------------------------------------------------------------------------
# beddel kit list --json
# ---------------------------------------------------------------------------


class TestKitListJson:
    """Tests for ``beddel kit list --json`` output."""

    def test_kit_list_json_output(self, tmp_path: Path) -> None:
        """``--json`` returns valid JSON with expected keys and types."""
        db_path = tmp_path / "index.db"
        _populate_kits(
            db_path,
            [
                {
                    "name": "my-kit",
                    "version": "2.0.0",
                    "category": "llm",
                    "port": "llm",
                    "enabled": 1,
                },
            ],
        )

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert set(item.keys()) == {"name", "version", "enabled", "category", "port"}
        assert item["name"] == "my-kit"
        assert item["version"] == "2.0.0"
        assert item["enabled"] is True
        assert item["category"] == "llm"
        assert item["port"] == "llm"

    def test_kit_list_json_disabled_kit(self, tmp_path: Path) -> None:
        """Disabled kit has ``enabled: false`` in JSON output."""
        db_path = tmp_path / "index.db"
        _populate_kits(
            db_path,
            [
                {
                    "name": "disabled-kit",
                    "version": "0.1.0",
                    "enabled": 0,
                },
            ],
        )

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["enabled"] is False

    def test_kit_list_json_empty_index(self, tmp_path: Path) -> None:
        """``--json`` with empty index returns ``[]``."""
        db_path = tmp_path / "index.db"
        store = IndexStore(db_path)
        asyncio.run(store._ensure_initialized())

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []


# ---------------------------------------------------------------------------
# beddel kit list — missing index.db
# ---------------------------------------------------------------------------


class TestKitListMissingIndex:
    """Tests for ``beddel kit list`` when index.db does not exist."""

    def test_kit_list_no_index_error(self, tmp_path: Path) -> None:
        """Missing index.db prints error and exits with code 1."""
        db_path = tmp_path / "nonexistent" / "index.db"
        assert not db_path.exists()

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 1
        assert "No index found" in result.output
        assert "beddel connect" in result.output

    def test_kit_list_json_no_index_error(self, tmp_path: Path) -> None:
        """Missing index.db with ``--json`` also prints error and exits 1."""
        db_path = tmp_path / "nonexistent" / "index.db"
        assert not db_path.exists()

        runner = CliRunner()
        with patch(_INDEX_STORE_DB_PATH, db_path):
            result = runner.invoke(cli, ["kit", "list", "--json"])

        assert result.exit_code == 1
        assert "No index found" in result.output
