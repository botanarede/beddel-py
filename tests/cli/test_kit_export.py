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
