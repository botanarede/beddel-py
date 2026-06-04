"""Bundled workflow assets shipped with the beddel package.

These workflows are always available regardless of kit installation
or flow path configuration. They are mounted by ``beddel setup`` and
discoverable by ``beddel launch``.

Bundled workflows:
  - setup.yaml: Interactive configuration wizard (A2UI form)
  - hello.yaml: Minimal LLM Q&A workflow
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = [
    "get_bundled_flows_dir",
    "get_bundled_workflow_path",
    "BUNDLED_WORKFLOWS",
]

BUNDLED_WORKFLOWS = ["setup", "hello"]
"""Names of workflows bundled with the beddel package."""


def get_bundled_workflow_path(name: str) -> Path:
    """Return the filesystem path to a bundled workflow YAML.

    Args:
        name: Workflow name without extension (e.g. "setup", "hello").

    Returns:
        Path to the YAML file.

    Raises:
        FileNotFoundError: If the named workflow is not bundled.
    """
    filename = f"{name}.yaml"
    ref = resources.files("beddel.flows").joinpath(filename)
    path = Path(str(ref))
    if not path.exists():
        msg = f"Bundled workflow '{name}' not found at {path}"
        raise FileNotFoundError(msg)
    return path


def get_bundled_flows_dir() -> Path:
    """Return the filesystem path to the bundled flows directory.

    All YAML files in this directory are discoverable by ``beddel launch``
    and ``beddel setup`` when bundled flow inclusion is enabled.
    """
    ref = resources.files("beddel.flows")
    return Path(str(ref))
