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

    # -- Skill metadata enrichment -----------------------------------------
    dependencies: list[str] = workflow_meta.get("dependencies", [])
    version_constraint = f">={version}"

    dep_lines = ""
    if dependencies:
        for dep in dependencies:
            dep_lines += f"  - {dep}\n"
    else:
        dep_lines = "  # none\n"

    metadata_block = (
        f"## Skill Metadata\n"
        f"\n"
        f"```yaml\n"
        f"dependencies:\n"
        f"{dep_lines}"
        f"governance:\n"
        f"  policy: permissive\n"
        f'version_constraint: "{version_constraint}"\n'
        f"```\n"
    )

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
        f"\n"
        f"{metadata_block}"
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

    Creates a ``server.py`` and ``README.md`` inside
    ``output_dir/mcp-servers/{kebab-name}/``.

    The generated ``server.py`` is scaffolding — a template the user
    will customise.  It does **not** need to be importable or runnable
    in the test environment.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.  Optional ``input_schema`` dict for
            generating typed function parameters.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated server.py file.
    """
    name: str = workflow_meta["name"]
    description: str = workflow_meta.get("description", "")
    version: str = workflow_meta.get("version", "1.0")
    workflow_id: str = workflow_meta.get("id", name)
    input_schema: dict[str, Any] | None = workflow_meta.get("input_schema")

    # Sanitise workflow id to a valid Python identifier
    func_name = workflow_id.replace("-", "_")

    dir_name = _to_kebab_case(name)
    mcp_dir = output_dir / "mcp-servers" / dir_name
    mcp_dir.mkdir(parents=True, exist_ok=True)

    # Build function parameters from input_schema if available
    properties = (input_schema or {}).get("properties", {})
    params = ", ".join(f"{p}: str" for p in properties) if properties else "inputs: str"

    # -- server.py ---------------------------------------------------------
    server_py = (
        f'"""FastMCP server for {name}."""\n'
        f"\n"
        f"from mcp.server.fastmcp import FastMCP\n"
        f"\n"
        f'mcp = FastMCP("{name}")\n'
        f"\n"
        f"\n"
        f"@mcp.tool()\n"
        f"async def {func_name}({params}) -> str:\n"
        f'    """{description}"""\n'
        f"    # TODO: Load and execute the workflow\n"
        f'    return "Not implemented"\n'
        f"\n"
        f"\n"
        f'if __name__ == "__main__":\n'
        f"    mcp.run()\n"
    )

    server_path = mcp_dir / "server.py"
    server_path.write_text(server_py)

    # -- README.md ---------------------------------------------------------
    readme_md = (
        f"# {name} MCP Server\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Installation\n"
        f"\n"
        f"```bash\n"
        f"pip install mcp\n"
        f"```\n"
        f"\n"
        f"## Running\n"
        f"\n"
        f"```bash\n"
        f"python server.py\n"
        f"```\n"
        f"\n"
        f"## MCP Client Configuration\n"
        f"\n"
        f"Add this to your MCP client config:\n"
        f"\n"
        f"```json\n"
        f"{{\n"
        f'  "mcpServers": {{\n'
        f'    "{dir_name}": {{\n'
        f'      "command": "python",\n'
        f'      "args": ["server.py"]\n'
        f"    }}\n"
        f"  }}\n"
        f"}}\n"
        f"```\n"
        f"\n"
        f"## Details\n"
        f"\n"
        f"- **Version:** {version}\n"
        f"- **Workflow:** `{workflow_id}`\n"
    )

    readme_path = mcp_dir / "README.md"
    readme_path.write_text(readme_md)

    return server_path


def export_endpoint(workflow_meta: dict[str, Any], output_dir: Path) -> Path:
    """Generate a standalone FastAPI app serving a workflow as a REST endpoint.

    Creates an ``app.py`` and ``README.md`` inside
    ``output_dir/endpoints/{kebab-name}/``.

    The generated ``app.py`` is scaffolding — a template the user
    will customise.  It does **not** need to be importable or runnable
    in the test environment.

    Args:
        workflow_meta: Workflow metadata with keys: name, description,
            version, id, steps.
        output_dir: Root directory for generated output.

    Returns:
        Path to the generated app.py file.
    """
    name: str = workflow_meta["name"]
    description: str = workflow_meta.get("description", "")
    version: str = workflow_meta.get("version", "1.0")
    workflow_id: str = workflow_meta.get("id", name)

    dir_name = _to_kebab_case(name)
    endpoint_dir = output_dir / "endpoints" / dir_name
    endpoint_dir.mkdir(parents=True, exist_ok=True)

    # -- app.py ------------------------------------------------------------
    app_py = (
        f'"""FastAPI endpoint for {name}."""\n'
        f"\n"
        f"from fastapi import FastAPI\n"
        f"\n"
        f'app = FastAPI(title="{name}")\n'
        f"\n"
        f"\n"
        f'@app.post("/{workflow_id}")\n'
        f"async def run_workflow(inputs: dict) -> dict:\n"  # noqa: E501
        f'    """{description}"""\n'
        f"    # TODO: Load and execute the workflow\n"
        f'    return {{"status": "ok"}}\n'
        f"\n"
        f"\n"
        f'if __name__ == "__main__":\n'
        f"    import uvicorn\n"
        f"\n"
        f"    uvicorn.run(app)\n"
    )

    app_path = endpoint_dir / "app.py"
    app_path.write_text(app_py)

    # -- README.md ---------------------------------------------------------
    readme_md = (
        f"# {name} Endpoint\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Installation\n"
        f"\n"
        f"```bash\n"
        f"pip install fastapi uvicorn\n"
        f"```\n"
        f"\n"
        f"## Running\n"
        f"\n"
        f"```bash\n"
        f"python app.py\n"
        f"```\n"
        f"\n"
        f"## Usage\n"
        f"\n"
        f"```bash\n"
        f"curl -X POST http://localhost:8000/{workflow_id} \\\n"
        f'  -H "Content-Type: application/json" \\\n'
        f'  -d \'{{"topic": "example"}}\'\n'
        f"```\n"
        f"\n"
        f"## Details\n"
        f"\n"
        f"- **Version:** {version}\n"
        f"- **Workflow:** `{workflow_id}`\n"
    )

    readme_path = endpoint_dir / "README.md"
    readme_path.write_text(readme_md)

    return app_path
