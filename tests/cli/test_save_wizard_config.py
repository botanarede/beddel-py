"""Tests for ``save_wizard_config`` (onboarding Apply persistence)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beddel.cli import config as config_mod


@pytest.fixture
def tmp_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the global config path at a temp file."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", path)
    return path


def test_save_wizard_config_writes_fields(tmp_config: Path) -> None:
    cfg_json = json.dumps(
        {
            "llm_provider": "gemini",
            "default_model": "gemini-2.0-flash",
            "project_name": "my-research",
            "features": ["memory", "reflection"],
        }
    )
    result = config_mod.save_wizard_config(cfg_json, name="Alice")

    assert result["saved"] is True
    saved = json.loads(tmp_config.read_text())
    assert saved["llm_provider"] == "gemini"
    assert saved["default_model"] == "gemini-2.0-flash"
    assert saved["project_name"] == "my-research"
    assert saved["features"] == ["memory", "reflection"]


def test_save_wizard_config_tolerates_fenced_json(tmp_config: Path) -> None:
    fenced = '```json\n{"llm_provider": "litellm", "default_model": "gpt-4o"}\n```'
    config_mod.save_wizard_config(fenced)
    saved = json.loads(tmp_config.read_text())
    assert saved["llm_provider"] == "litellm"
    assert saved["default_model"] == "gpt-4o"


def test_save_wizard_config_provider_fallback(tmp_config: Path) -> None:
    """When config_json omits the provider, the explicit provider arg is used."""
    config_mod.save_wizard_config('{"default_model": "x"}', provider="gemini")
    saved = json.loads(tmp_config.read_text())
    assert saved["llm_provider"] == "gemini"


def test_save_wizard_config_roundtrips_via_load(tmp_config: Path) -> None:
    """Saved wizard fields are loadable via load_global_config."""
    config_mod.save_wizard_config('{"llm_provider": "gemini", "project_name": "demo"}')
    loaded = config_mod.load_global_config()
    assert loaded["llm_provider"] == "gemini"
    assert loaded["project_name"] == "demo"
