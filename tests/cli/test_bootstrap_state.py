"""Tests for the bootstrap pre-flight state and flow isolation.

The ``beddel launch`` pre-flight asks two questions, not one: is the
database provisioned, and are the kits that serve the wizard installed?
These tests pin both halves, the removal of the legacy config.json
shortcut, and the first-run isolation of configured flow paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from beddel.cli.commands import cli
from beddel.cli.init import (
    PROVIDER_KITS,
    REQUIRED_KITS,
    base_kits_present,
    is_bootstrapped,
)

_ALL_GEMINI_KITS = [k["name"] for k in REQUIRED_KITS + PROVIDER_KITS["gemini"]]


def _install_fake_kits(kits_dir: Path, names: list[str]) -> None:
    """Create the minimum on-disk shape that counts as an installed kit."""
    for name in names:
        kit = kits_dir / name
        kit.mkdir(parents=True, exist_ok=True)
        (kit / "kit.yaml").write_text(f"name: {name}\nversion: 0.1.0\n")


# ---------------------------------------------------------------------------
# base_kits_present — the half the original guard forgot
# ---------------------------------------------------------------------------


def test_base_kits_absent_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no kits_paths configured there is nothing to discover."""
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [])
    assert base_kits_present() is False


def test_base_kits_absent_when_only_some_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partial install does not satisfy the pre-flight."""
    _install_fake_kits(tmp_path, [REQUIRED_KITS[0]["name"]])
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [tmp_path])
    assert base_kits_present("gemini") is False


def test_base_kits_absent_without_the_provider_kit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The provider kit is required: without an LLM the example flows fail.

    This is the case the first version of the check missed — the two base
    kits are enough to SERVE a page, so the environment looked ready while
    every flow with an ``llm`` step would fail.
    """
    _install_fake_kits(tmp_path, [k["name"] for k in REQUIRED_KITS])
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [tmp_path])
    assert base_kits_present("gemini") is False


def test_base_kits_present_when_all_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Base kits plus the provider kit satisfy the check."""
    _install_fake_kits(tmp_path, _ALL_GEMINI_KITS)
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [tmp_path])
    assert base_kits_present("gemini") is True


def test_base_kits_follows_the_configured_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no provider argument, the configured provider decides the check."""
    _install_fake_kits(tmp_path, _ALL_GEMINI_KITS)
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [tmp_path])

    monkeypatch.setattr("beddel.cli.config.resolve_llm_provider", lambda: "gemini")
    assert base_kits_present() is True

    # litellm needs a kit that is not installed here
    monkeypatch.setattr("beddel.cli.config.resolve_llm_provider", lambda: "litellm")
    assert base_kits_present() is False


def test_is_bootstrapped_needs_both_halves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A provisioned database alone is not enough — the kits serve the runner."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("beddel.cli.init.BEDDEL_DATA_DIR", data_dir)
    monkeypatch.setattr("beddel.cli.config.resolve_llm_provider", lambda: "gemini")

    kits_dir = tmp_path / "kits"
    _install_fake_kits(kits_dir, _ALL_GEMINI_KITS)

    # Database missing, kits present
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [kits_dir])
    assert is_bootstrapped() is False

    # Database present, kits missing
    (data_dir / "index.db").write_text("")
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [tmp_path / "empty"])
    assert is_bootstrapped() is False

    # Both present
    monkeypatch.setattr("beddel.cli.config.resolve_kits_paths", lambda: [kits_dir])
    assert is_bootstrapped() is True


# ---------------------------------------------------------------------------
# Legacy shortcut removal
# ---------------------------------------------------------------------------


def test_onboarding_not_complete_from_config_project_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``project_name`` in config.json no longer skips the wizard.

    The old fallback treated an unreadable store plus a legacy config key
    as proof of a finished onboarding, which silently suppressed the
    wizard on any machine carrying an older config file.
    """
    from beddel.cli import config as config_mod

    monkeypatch.setattr(
        config_mod, "load_global_config", lambda: {"project_name": "legacy-project"}
    )

    class _Boom:
        def __init__(self, *_a, **_k):
            raise OSError("store unreadable")

    monkeypatch.setattr("beddel.adapters.index_store.IndexStore", _Boom)

    assert config_mod.is_onboarding_complete() is False


# ---------------------------------------------------------------------------
# init: the non-interactive path requires an explicit provider
# ---------------------------------------------------------------------------


def test_init_requires_explicit_provider() -> None:
    """There is no silent default provider — the caller must choose one."""
    result = CliRunner().invoke(cli, ["init", "--yes"])

    assert result.exit_code != 0
    assert "--provider" in result.output


def test_init_rejects_unknown_provider() -> None:
    """An unsupported provider is refused rather than silently accepted."""
    result = CliRunner().invoke(cli, ["init", "--yes", "--provider", "nope"])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# _persist_kits_dir — the chosen directory is the consent
# ---------------------------------------------------------------------------


def test_persist_kits_dir_writes_global_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The chosen directory replaces kits_paths in the global config."""
    from beddel.cli import config as config_mod
    from beddel.cli.init import _persist_kits_dir

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"kits_paths": ["/old/place"], "dev": True}) + "\n")
    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_mod, "find_project_config", lambda *_a, **_k: None)

    chosen = tmp_path / "chosen"
    _persist_kits_dir(chosen)

    written = json.loads(cfg_path.read_text())
    assert written["kits_paths"] == [str(chosen)]
    assert written["dev"] is True, "unrelated keys survive the write"


def test_persist_kits_dir_respects_project_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A project-local kits_paths wins, so the global file is left alone."""
    from beddel.cli import config as config_mod
    from beddel.cli.init import _persist_kits_dir

    project_cfg = tmp_path / ".beddel.json"
    project_cfg.write_text(json.dumps({"kits_paths": ["kits"]}) + "\n")
    global_cfg = tmp_path / "config.json"
    global_cfg.write_text(json.dumps({"kits_paths": ["/untouched"]}) + "\n")

    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)
    monkeypatch.setattr(config_mod, "find_project_config", lambda *_a, **_k: project_cfg)

    _persist_kits_dir(tmp_path / "ignored")

    assert json.loads(global_cfg.read_text())["kits_paths"] == ["/untouched"]


# ---------------------------------------------------------------------------
# only_explicit — configured flows must not reach the wizard menu
# ---------------------------------------------------------------------------


def _write_flow(path: Path, flow_id: str) -> Path:
    """Write a schema-valid minimal workflow."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""id: {flow_id}
name: {flow_id.replace("_", " ").title()}
description: Minimal workflow used as a discovery fixture.
version: "1.0"
input_schema:
  type: object
  properties: {{}}
  required: []
steps:
  - id: noop
    primitive: tool
    config:
      tool: noop_tool
      arguments: {{}}
"""
    )
    return path


def test_example_workflows_exclude_the_setup_wizard() -> None:
    """Setup is configured in the terminal, so it is not a browser example.

    The provider question decides which provider kit gets installed, and a
    browser form cannot install a kit — so re-asking there would let a user
    select a provider whose kit is absent.
    """
    from beddel.flows import BUNDLED_WORKFLOWS, EXAMPLE_WORKFLOWS

    assert "setup" not in EXAMPLE_WORKFLOWS
    assert "setup" in BUNDLED_WORKFLOWS, "still runnable via: beddel run --bundled setup"
    assert len(EXAMPLE_WORKFLOWS) == 3
    assert set(EXAMPLE_WORKFLOWS) <= set(BUNDLED_WORKFLOWS)


def test_every_example_workflow_ships_in_the_package() -> None:
    """Each advertised example resolves to a real bundled file."""
    from beddel.flows import EXAMPLE_WORKFLOWS, get_bundled_workflow_path

    for name in EXAMPLE_WORKFLOWS:
        path = get_bundled_workflow_path(name)
        assert path.exists(), f"example '{name}' is advertised but missing"
        assert path.suffix == ".yaml"
