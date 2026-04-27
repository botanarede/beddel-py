"""Tests for resolve_llm_provider — 4-layer resolution with user_prefs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from beddel.adapters.index_store import IndexStore
from beddel.cli import config as config_mod

# ---------------------------------------------------------------------------
# Helper: create a minimal index.db with user_prefs table
# ---------------------------------------------------------------------------


def _create_index_db(db_path: Path, prefs: dict[str, str] | None = None) -> None:
    """Create a minimal index.db with user_prefs table and optional data."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_prefs ("
        "key TEXT PRIMARY KEY, "
        "value TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
    if prefs:
        now = datetime.now(tz=UTC).isoformat()
        for key, value in prefs.items():
            conn.execute(
                "INSERT INTO user_prefs (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# resolve_llm_provider — user_prefs layer wins
# ---------------------------------------------------------------------------


class TestResolveLlmProviderUserPrefs:
    """user_prefs layer takes priority over all other layers."""

    def test_returns_user_prefs_value_when_set(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Set up index.db with llm_provider pref
        db_path = tmp_path / "index.db"
        _create_index_db(db_path, prefs={"llm_provider": "openai"})

        # Patch _DEFAULT_DB_PATH so IndexStore() uses our tmp db
        mp.setattr(
            "beddel.adapters.index_store._DEFAULT_DB_PATH",
            db_path,
        )
        # Also patch the default parameter on __init__
        original_init = IndexStore.__init__

        def _patched_init(self: IndexStore, db_path: object = tmp_path / "index.db") -> None:
            original_init(self, db_path)  # type: ignore[arg-type]

        mp.setattr(IndexStore, "__init__", _patched_init)

        # Project config with different value — should be ignored
        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"llm_provider": "anthropic"}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        # Global config with different value — should be ignored
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "cohere"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "openai"

    def test_user_prefs_overrides_project_and_global(
        self, monkeypatch: object, tmp_path: Path
    ) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        db_path = tmp_path / "index.db"
        _create_index_db(db_path, prefs={"llm_provider": "claude"})

        mp.setattr(
            "beddel.adapters.index_store._DEFAULT_DB_PATH",
            db_path,
        )
        original_init = IndexStore.__init__

        def _patched_init(self: IndexStore, db_path: object = tmp_path / "index.db") -> None:
            original_init(self, db_path)  # type: ignore[arg-type]

        mp.setattr(IndexStore, "__init__", _patched_init)

        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"llm_provider": "gemini"}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "openai"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "claude"


# ---------------------------------------------------------------------------
# resolve_llm_provider — fallback to .beddel.json
# ---------------------------------------------------------------------------


class TestResolveLlmProviderProjectFallback:
    """Falls back to .beddel.json when user_prefs has no value."""

    def test_falls_back_to_project_config(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # index.db exists but no llm_provider pref
        db_path = tmp_path / "index.db"
        _create_index_db(db_path, prefs={})

        mp.setattr(
            "beddel.adapters.index_store._DEFAULT_DB_PATH",
            db_path,
        )
        original_init = IndexStore.__init__

        def _patched_init(self: IndexStore, db_path: object = tmp_path / "index.db") -> None:
            original_init(self, db_path)  # type: ignore[arg-type]

        mp.setattr(IndexStore, "__init__", _patched_init)

        # Project config has llm_provider
        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"llm_provider": "anthropic"}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "openai"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "anthropic"


# ---------------------------------------------------------------------------
# resolve_llm_provider — fallback to config.json
# ---------------------------------------------------------------------------


class TestResolveLlmProviderGlobalFallback:
    """Falls back to config.json when user_prefs and .beddel.json are empty."""

    def test_falls_back_to_global_config(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # index.db exists but no llm_provider pref
        db_path = tmp_path / "index.db"
        _create_index_db(db_path, prefs={})

        mp.setattr(
            "beddel.adapters.index_store._DEFAULT_DB_PATH",
            db_path,
        )
        original_init = IndexStore.__init__

        def _patched_init(self: IndexStore, db_path: object = tmp_path / "index.db") -> None:
            original_init(self, db_path)  # type: ignore[arg-type]

        mp.setattr(IndexStore, "__init__", _patched_init)

        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)

        # Global config has llm_provider
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "openai"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "openai"


# ---------------------------------------------------------------------------
# resolve_llm_provider — fallback to default
# ---------------------------------------------------------------------------


class TestResolveLlmProviderDefault:
    """Falls back to default 'gemini' when all layers are empty."""

    def test_returns_default_when_all_empty(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # index.db exists but no llm_provider pref
        db_path = tmp_path / "index.db"
        _create_index_db(db_path, prefs={})

        mp.setattr(
            "beddel.adapters.index_store._DEFAULT_DB_PATH",
            db_path,
        )
        original_init = IndexStore.__init__

        def _patched_init(self: IndexStore, db_path: object = tmp_path / "index.db") -> None:
            original_init(self, db_path)  # type: ignore[arg-type]

        mp.setattr(IndexStore, "__init__", _patched_init)

        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)

        # Global config without llm_provider
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"kits_paths": []}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "gemini"


# ---------------------------------------------------------------------------
# resolve_llm_provider — graceful degradation
# ---------------------------------------------------------------------------


class TestResolveLlmProviderGracefulDegradation:
    """Graceful degradation when index.db is missing or corrupt."""

    def test_falls_back_when_index_db_corrupt(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Create a corrupt db file
        corrupt_db = tmp_path / "corrupt.db"
        corrupt_db.write_text("this is not a valid sqlite database")

        original_init = IndexStore.__init__

        def _patched_init(self: IndexStore, db_path: object = corrupt_db) -> None:
            original_init(self, db_path)  # type: ignore[arg-type]

        mp.setattr(IndexStore, "__init__", _patched_init)

        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)

        # Global config has llm_provider — should be used as fallback
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "anthropic"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "anthropic"

    def test_falls_back_to_default_when_all_fail(
        self, monkeypatch: object, tmp_path: Path
    ) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Make IndexStore raise on construction
        def _raise_init(self: object, db_path: object = None) -> None:
            raise OSError("cannot access index.db")

        mp.setattr(IndexStore, "__init__", _raise_init)

        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)

        # No global config
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "missing.json")

        assert config_mod.resolve_llm_provider() == "gemini"

    def test_falls_back_when_asyncio_run_raises(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Patch asyncio.run to raise
        def _failing_run(coro: object) -> None:
            # Close the coroutine to avoid warning
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]
            raise RuntimeError("event loop error")

        mp.setattr("asyncio.run", _failing_run)

        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)

        # Global config has llm_provider
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "cohere"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "cohere"

    def test_falls_back_when_get_pref_raises(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Patch get_pref to raise
        async def _failing_get_pref(self: object, key: str) -> str | None:
            raise sqlite3.DatabaseError("database disk image is malformed")

        mp.setattr(IndexStore, "get_pref", _failing_get_pref)

        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)

        # Global config has llm_provider
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"llm_provider": "openai"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_llm_provider() == "openai"
