"""Smoke E2E tests for the init → setup onboarding flow.

The ``test_init`` case performs a real ``beddel init`` (git clone + pip)
and is gated behind the ``integration`` marker (run with
``--run-integration``).  The serve-app case is deterministic and runs in
the normal suite, proving the renderer (``GET /``) and launcher
(``GET /workflows``) expose the onboarding workflow.
"""

from __future__ import annotations

import importlib.metadata
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from beddel.domain.kit import KitDiscoveryResult
from beddel.flows import get_onboarding_workflow_path


@pytest.mark.integration
def test_init_downloads_kits_and_deps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`beddel init --yes --provider gemini` provisions kits with python/ + deps."""
    if shutil.which("git") is None:
        pytest.skip("git not available")

    from click.testing import CliRunner

    from beddel.cli import init as init_mod
    from beddel.cli.commands import cli

    data_dir = tmp_path / "beddel"
    kits_dir = data_dir / "kits"
    monkeypatch.setattr(init_mod, "BEDDEL_DATA_DIR", data_dir)
    monkeypatch.setattr(init_mod, "DEFAULT_KITS_DIR", kits_dir)

    result = CliRunner().invoke(cli, ["init", "--yes", "--provider", "gemini"])

    assert result.exit_code == 0, result.output
    assert (kits_dir / "serve-fastapi-kit" / "python").is_dir()
    # Gemini provider dependency installed into the environment.
    assert importlib.metadata.version("google-genai")


def test_serve_app_renders_and_lists_onboarding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The serve app exposes the A2UI renderer and lists the onboarding workflow."""
    # Stub heavy discovery; force index degraded so flows mount without filtering.
    monkeypatch.setattr("beddel.cli.commands._ensure_kit_paths", lambda: None)
    monkeypatch.setattr("beddel.cli.commands._validate_config_paths", lambda: None)
    monkeypatch.setattr("beddel.cli.commands._resolve_all_kit_paths", lambda _k: [])
    monkeypatch.setattr(
        "beddel.cli.commands._resolve_all_flow_paths",
        lambda _w: (get_onboarding_workflow_path(),),
    )
    monkeypatch.setattr(
        "beddel.tools.kits.discover_kits",
        lambda _p: KitDiscoveryResult(manifests=[], collisions=[]),
    )
    monkeypatch.setattr(
        "beddel.cli.commands._build_adapter_registries", lambda _dr, **_k: ({}, None)
    )
    monkeypatch.setattr("beddel.cli.commands._parse_tool_flags", lambda _t: {})
    monkeypatch.setattr("beddel.cli.commands._build_tool_registry", lambda *_a, **_k: {})

    class _NoIndex:
        def __init__(self, *_a: object, **_k: object) -> None:
            raise OSError("index unavailable")

    monkeypatch.setattr("beddel.adapters.index_store.IndexStore", _NoIndex)

    from beddel.cli.commands import _build_runtime_app

    app, _loaded, wf_ids = _build_runtime_app((get_onboarding_workflow_path(),), no_kits=True)
    assert "beddel_onboarding" in wf_ids

    client = TestClient(app)

    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]

    listing = client.get("/workflows")
    assert listing.status_code == 200
    assert "beddel_onboarding" in [wf["id"] for wf in listing.json()]
