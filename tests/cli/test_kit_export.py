"""Tests for ``beddel kit export`` CLI command — skill format.

Uses click.testing.CliRunner to invoke the CLI and verifies
generated output files have correct structure and content.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from beddel.cli.commands import cli

FIXTURE = Path(__file__).resolve().parents[4] / "spec" / "fixtures" / "valid" / "simple.yaml"


class TestExportSkill:
    """Tests for ``beddel kit export --format skill``."""

    def test_export_skill(self, tmp_path: Path) -> None:
        """Skill export creates SKILL.md and README.md with correct content."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["kit", "export", str(FIXTURE), "--format", "skill", "-o", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output

        skill_dir = tmp_path / ".agents" / "skills" / "simple-llm-workflow"
        skill_md = skill_dir / "SKILL.md"
        readme_md = skill_dir / "README.md"

        # Both files must exist
        assert skill_md.exists(), f"SKILL.md not found in {skill_dir}"
        assert readme_md.exists(), f"README.md not found in {skill_dir}"

        # SKILL.md — frontmatter with name and description
        skill_content = skill_md.read_text()
        assert skill_content.startswith("---\n")
        assert "name: Simple LLM Workflow" in skill_content
        assert "description: A minimal workflow" in skill_content
        # Closing frontmatter delimiter
        assert skill_content.count("---") >= 2

        # SKILL.md — step references
        assert "generate" in skill_content
        assert "llm" in skill_content

        # README.md — usage instructions
        readme_content = readme_md.read_text()
        assert "Simple LLM Workflow" in readme_content
        assert "Add this skill to your agent" in readme_content
        assert "simple-llm-workflow" in readme_content

    def test_export_skill_kebab_case_dir(self, tmp_path: Path) -> None:
        """Workflow name is sanitized to kebab-case for the directory."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["kit", "export", str(FIXTURE), "--format", "skill", "-o", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output

        # "Simple LLM Workflow" → "simple-llm-workflow"
        skill_dir = tmp_path / ".agents" / "skills" / "simple-llm-workflow"
        assert skill_dir.is_dir(), f"Expected kebab-case dir: {skill_dir}"


class TestExportKit:
    """Tests for ``beddel kit export --format kit``."""

    def test_export_kit(self, tmp_path: Path) -> None:
        """Kit export creates kit.yaml, copies workflow, and generates README."""
        import yaml

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["kit", "export", str(FIXTURE), "--format", "kit", "-o", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output

        kit_dir = tmp_path / "kits" / "simple-llm-workflow-kit"

        # kit.yaml must exist and contain required fields
        kit_yaml = kit_dir / "kit.yaml"
        assert kit_yaml.exists(), f"kit.yaml not found in {kit_dir}"

        manifest = yaml.safe_load(kit_yaml.read_text())
        assert manifest["name"] == "simple-llm-workflow-kit"
        assert manifest["version"] == "1.0"
        expected_desc = "A minimal workflow that generates content about a given topic."
        assert manifest["description"] == expected_desc
        assert "workflows" in manifest
        assert len(manifest["workflows"]) == 1
        assert manifest["workflows"][0]["name"] == "Simple LLM Workflow"
        assert "workflows/simple.yaml" in manifest["workflows"][0]["path"]

        # Workflow file must be copied
        workflow_copy = kit_dir / "workflows" / "simple.yaml"
        assert workflow_copy.exists(), f"Workflow file not copied to {workflow_copy}"

        copied = yaml.safe_load(workflow_copy.read_text())
        assert copied["name"] == "Simple LLM Workflow"
        assert "steps" in copied

        # README.md must exist with usage instructions
        readme = kit_dir / "README.md"
        assert readme.exists(), f"README.md not found in {kit_dir}"

        readme_content = readme.read_text()
        assert "simple-llm-workflow-kit" in readme_content
        assert "beddel kit install" in readme_content
        assert "beddel run" in readme_content


class TestExportMcp:
    """Tests for ``beddel kit export --format mcp``."""

    def test_export_mcp(self, tmp_path: Path) -> None:
        """MCP export creates server.py and README.md with correct content."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["kit", "export", str(FIXTURE), "--format", "mcp", "-o", str(tmp_path)],
        )

        assert result.exit_code == 0, result.output

        mcp_dir = tmp_path / "mcp-servers" / "simple-llm-workflow"
        server_py = mcp_dir / "server.py"
        readme_md = mcp_dir / "README.md"

        # Both files must exist
        assert server_py.exists(), f"server.py not found in {mcp_dir}"
        assert readme_md.exists(), f"README.md not found in {mcp_dir}"

        # server.py — FastMCP import
        server_content = server_py.read_text()
        assert "from mcp.server.fastmcp import FastMCP" in server_content

        # server.py — tool decorator
        assert "@mcp.tool()" in server_content

        # server.py — main block
        assert 'if __name__ == "__main__"' in server_content
        assert "mcp.run()" in server_content

        # server.py — workflow name in server instance
        assert "Simple LLM Workflow" in server_content

        # server.py — function uses sanitised workflow id
        assert "def simple_llm(" in server_content

        # server.py — input parameters from input_schema
        assert "topic: str" in server_content

        # server.py — docstring with description
        assert "A minimal workflow" in server_content

        # README.md — install instructions
        readme_content = readme_md.read_text()
        assert "pip install mcp" in readme_content
        assert "python server.py" in readme_content
        assert "Simple LLM Workflow" in readme_content
