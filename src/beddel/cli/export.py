"""Kit export generators for workflow scaffolding.

Each generator takes workflow metadata and an output directory,
then produces format-specific scaffolding files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _to_kebab_case(name: str) -> str:
    """Sanitize a name to kebab-case for directory naming."""
    import re

    # Replace non-alphanumeric chars (except hyphens) with hyphens
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", name.strip())
    # Collapse consecutive hyphens and strip leading/trailing
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug.lower()


def export_skill(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a BMAD skill from a workflow.

    Creates a ``SKILL.md`` file with YAML frontmatter and step
    instructions, plus a ``README.md`` with usage guidance, inside
    ``output_dir/.agents/skills/{kebab-name}/``.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated SKILL.md file.
    """
    name: str = workflow_meta["name"]
    description: str = workflow_meta.get("description", "")
    version: str = workflow_meta.get("version", "1.0")
    workflow_id: str = workflow_meta.get("id", name)
    steps: list[dict[str, Any]] = workflow_meta.get("steps", [])

    dir_name = _to_kebab_case(name)
    skill_dir = output_dir / ".agents" / "skills" / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    # -- SKILL.md ----------------------------------------------------------
    step_lines = ""
    for i, step in enumerate(steps, 1):
        step_id = step.get("id", f"step-{i}")
        primitive = step.get("primitive", "unknown")
        config = step.get("config", {})
        brief = config.get("prompt", config.get("description", ""))
        if brief:
            # Truncate long prompts for readability
            brief = (brief[:80] + "…") if len(brief) > 80 else brief
            step_lines += f"{i}. **{step_id}** (`{primitive}`) — {brief}\n"
        else:
            step_lines += f"{i}. **{step_id}** (`{primitive}`)\n"

    skill_md = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"---\n"
        f"\n"
        f"# {name}\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Steps\n"
        f"\n"
        f"{step_lines}"
    )

    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_md)

    # -- README.md ---------------------------------------------------------
    readme_md = (
        f"# {name}\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Usage\n"
        f"\n"
        f"Add this skill to your agent's skills directory:\n"
        f"\n"
        f"```bash\n"
        f"cp -r .agents/skills/{dir_name} <your-project>/.agents/skills/\n"
        f"```\n"
        f"\n"
        f"## Details\n"
        f"\n"
        f"- **Version:** {version}\n"
        f"- **Workflow source:** `{workflow_id}`\n"
    )

    readme_path = skill_dir / "README.md"
    readme_path.write_text(readme_md)

    return skill_path


def export_kit(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a solution kit wrapping a workflow.

    Creates a ``kit.yaml`` manifest, copies the source workflow YAML
    into a ``workflows/`` subdirectory, and generates a ``README.md``
    inside ``output_dir/kits/{kebab-name}-kit/``.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.  Optional ``source_path`` (Path) points
            to the original workflow file for copying.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated kit.yaml file.
    """
    import shutil

    import yaml

    name: str = workflow_meta["name"]
    description: str = workflow_meta.get("description", "")
    version: str = workflow_meta.get("version", "1.0")
    source_path: Path | None = workflow_meta.get("source_path")

    dir_name = _to_kebab_case(name)
    kit_name = f"{dir_name}-kit"
    kit_dir = output_dir / "kits" / kit_name
    kit_dir.mkdir(parents=True, exist_ok=True)

    # Determine workflow filename
    workflow_file = source_path.name if source_path else f"{dir_name}.yaml"

    # -- kit.yaml ----------------------------------------------------------
    kit_manifest: dict[str, Any] = {
        "name": kit_name,
        "version": version,
        "description": description,
        "workflows": [
            {
                "name": name,
                "path": f"workflows/{workflow_file}",
            },
        ],
    }

    kit_yaml_path = kit_dir / "kit.yaml"
    kit_yaml_path.write_text(yaml.dump(kit_manifest, sort_keys=False))

    # -- workflows/{file} --------------------------------------------------
    workflows_dir = kit_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    if source_path and source_path.exists():
        shutil.copy2(source_path, workflows_dir / workflow_file)
    else:
        # Fallback: serialise the steps we have
        (workflows_dir / workflow_file).write_text(
            yaml.dump({"name": name, "steps": workflow_meta.get("steps", [])}, sort_keys=False)
        )

    # -- README.md ---------------------------------------------------------
    readme_md = (
        f"# {kit_name}\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Installation\n"
        f"\n"
        f"```bash\n"
        f"beddel kit install kits/{kit_name}/\n"
        f"```\n"
        f"\n"
        f"## Workflow Usage\n"
        f"\n"
        f"```bash\n"
        f"beddel run workflows/{workflow_file}\n"
        f"```\n"
        f"\n"
        f"## Details\n"
        f"\n"
        f"- **Version:** {version}\n"
        f"- **Workflow:** `{name}`\n"
    )

    readme_path = kit_dir / "README.md"
    readme_path.write_text(readme_md)

    return kit_yaml_path


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
