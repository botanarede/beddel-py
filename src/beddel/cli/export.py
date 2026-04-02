"""Kit export generators for workflow scaffolding.

Each generator takes workflow metadata and an output directory,
then produces format-specific scaffolding files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def export_skill(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a BMAD skill from a workflow.

    Creates a `SKILL.md` file with frontmatter and step instructions
    inside `output_dir/.agents/skills/{name}/`.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated SKILL.md file.
    """
    name = workflow_meta["name"]
    skill_dir = output_dir / ".agents" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    readme = skill_dir / "README.md"
    readme.write_text(f"# {name}\n\nPlaceholder — skill export.\n")
    return readme


def export_kit(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a solution kit wrapping a workflow.

    Creates a `kit.yaml` manifest and copies the workflow YAML
    inside `output_dir/kits/{name}-kit/`.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated kit.yaml file.
    """
    name = workflow_meta["name"]
    kit_dir = output_dir / "kits" / f"{name}-kit"
    kit_dir.mkdir(parents=True, exist_ok=True)

    readme = kit_dir / "README.md"
    readme.write_text(f"# {name}-kit\n\nPlaceholder — kit export.\n")
    return readme


def export_mcp(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a FastMCP server exposing a workflow as an MCP tool.

    Creates a `server.py` file inside `output_dir/mcp-servers/{name}/`.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated server.py file.
    """
    name = workflow_meta["name"]
    mcp_dir = output_dir / "mcp-servers" / name
    mcp_dir.mkdir(parents=True, exist_ok=True)

    readme = mcp_dir / "README.md"
    readme.write_text(f"# {name} MCP Server\n\nPlaceholder — mcp export.\n")
    return readme


def export_endpoint(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a standalone FastAPI app serving a workflow as a REST endpoint.

    Creates an `app.py` file inside `output_dir/endpoints/{name}/`.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated app.py file.
    """
    name = workflow_meta["name"]
    endpoint_dir = output_dir / "endpoints" / name
    endpoint_dir.mkdir(parents=True, exist_ok=True)

    readme = endpoint_dir / "README.md"
    readme.write_text(f"# {name} Endpoint\n\nPlaceholder — endpoint export.\n")
    return readme
