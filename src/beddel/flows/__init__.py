"""Bundled workflow assets shipped with the beddel package."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def get_onboarding_workflow_path() -> Path:
    """Return the filesystem path to the bundled onboarding.yaml.

    Uses importlib.resources for reliable access regardless of
    installation method (wheel, editable, zipapp).
    """
    ref = resources.files("beddel.flows").joinpath("onboarding.yaml")
    return Path(str(ref))
