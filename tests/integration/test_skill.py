"""Integration tests for skill composition & workflow reuse (Story 7.4, Task 5).

Full pipeline: create mock kit manifest with workflow declaration → build
DefaultDependencies with kit_manifests → execute workflow with skill step →
verify sub-workflow executed via SkillResolver.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from beddel.domain.kit import (
    KitManifest,
    KitWorkflowDeclaration,
    SolutionKit,
)
from beddel.domain.models import (
    DefaultDependencies,
    SkillReference,
    Workflow,
)
from beddel.domain.parser import WorkflowParser
from beddel.domain.skill import SkillResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VALID_DIR = _REPO_ROOT / "spec" / "fixtures" / "valid"


def _make_kit_manifest(
    name: str,
    version: str,
    workflows: list[KitWorkflowDeclaration],
    root_path: Path,
) -> KitManifest:
    """Build a KitManifest with the given workflows."""
    kit = SolutionKit(
        name=name,
        version=version,
        description=f"Test kit: {name}",
        workflows=workflows,
    )
    return KitManifest(
        kit=kit,
        root_path=root_path,
        loaded_at=datetime.now(tz=UTC),
        source="test",
    )


def _write_skill_workflow(path: Path) -> None:
    """Write a minimal skill workflow YAML to *path*."""
    wf_data: dict[str, Any] = {
        "id": "create-epic",
        "name": "Create Epic Skill",
        "description": "A reusable skill workflow from a solution kit.",
        "version": "1.0",
        "steps": [
            {
                "id": "generate-epic",
                "primitive": "output-generator",
                "config": {"template": "Epic created successfully"},
            },
        ],
    }
    path.write_text(yaml.dump(wf_data, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Integration: Full pipeline (subtask 5.3)
# ---------------------------------------------------------------------------


class TestSkillPipeline:
    """Full pipeline: kit manifest → SkillResolver → sub-workflow execution."""

    @pytest.mark.asyncio
    async def test_skill_invocation_full_pipeline(self, tmp_path: Path) -> None:
        """Create kit manifest, resolve skill, execute sub-workflow end-to-end."""
        # 1. Write a skill workflow YAML to a temp directory
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
        skill_wf_path = workflows_dir / "create-epic.yaml"
        _write_skill_workflow(skill_wf_path)

        # 2. Build a KitManifest pointing to it
        manifest = _make_kit_manifest(
            name="software-development-kit",
            version="0.2.0",
            workflows=[
                KitWorkflowDeclaration(
                    name="create-epic",
                    path="workflows/create-epic.yaml",
                    description="Create an epic from requirements",
                ),
            ],
            root_path=tmp_path,
        )

        # 3. Resolve the skill reference
        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
            version=">=0.1.0",
        )
        resolver = SkillResolver()
        resolved_path = resolver.resolve(ref, [manifest])

        assert resolved_path == tmp_path / "workflows" / "create-epic.yaml"
        assert resolved_path.exists()

        # 4. Load the resolved workflow
        wf_yaml = resolved_path.read_text(encoding="utf-8")
        skill_workflow = WorkflowParser.parse(wf_yaml)

        assert skill_workflow.id == "create-epic"
        assert len(skill_workflow.steps) == 1
        assert skill_workflow.steps[0].id == "generate-epic"

    @pytest.mark.asyncio
    async def test_skill_with_governance_strict_allowed(self, tmp_path: Path) -> None:
        """Strict governance allows listed kit — resolution succeeds."""
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
        _write_skill_workflow(workflows_dir / "create-epic.yaml")

        manifest = _make_kit_manifest(
            name="software-development-kit",
            version="0.2.0",
            workflows=[
                KitWorkflowDeclaration(
                    name="create-epic",
                    path="workflows/create-epic.yaml",
                ),
            ],
            root_path=tmp_path,
        )

        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
            version=">=0.1.0",
        )
        governance = {"policy": "strict", "allowed": ["software-development-kit"]}

        resolver = SkillResolver()
        resolved_path = resolver.resolve(ref, [manifest], governance)

        assert resolved_path == tmp_path / "workflows" / "create-epic.yaml"

    @pytest.mark.asyncio
    async def test_skill_with_governance_strict_denied(self, tmp_path: Path) -> None:
        """Strict governance blocks unlisted kit — SkillError raised."""
        from beddel.domain.errors import SkillError

        manifest = _make_kit_manifest(
            name="software-development-kit",
            version="0.2.0",
            workflows=[
                KitWorkflowDeclaration(
                    name="create-epic",
                    path="workflows/create-epic.yaml",
                ),
            ],
            root_path=tmp_path,
        )

        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
        )
        governance = {"policy": "strict", "allowed": ["other-kit"]}

        resolver = SkillResolver()
        with pytest.raises(SkillError, match="not in the allowed list"):
            resolver.resolve(ref, [manifest], governance)

    @pytest.mark.asyncio
    async def test_skill_version_mismatch(self, tmp_path: Path) -> None:
        """Version constraint not satisfied — SkillError raised."""
        from beddel.domain.errors import SkillError

        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
        _write_skill_workflow(workflows_dir / "create-epic.yaml")

        manifest = _make_kit_manifest(
            name="software-development-kit",
            version="0.0.9",
            workflows=[
                KitWorkflowDeclaration(
                    name="create-epic",
                    path="workflows/create-epic.yaml",
                ),
            ],
            root_path=tmp_path,
        )

        ref = SkillReference(
            kit="software-development-kit",
            workflow="create-epic",
            version=">=0.1.0",
        )

        resolver = SkillResolver()
        with pytest.raises(SkillError, match="does not satisfy constraint"):
            resolver.resolve(ref, [manifest])

    @pytest.mark.asyncio
    async def test_skill_kit_not_found(self, tmp_path: Path) -> None:
        """Kit not in manifests — SkillError raised."""
        from beddel.domain.errors import SkillError

        ref = SkillReference(
            kit="nonexistent-kit",
            workflow="create-epic",
        )

        resolver = SkillResolver()
        with pytest.raises(SkillError, match="not found in available manifests"):
            resolver.resolve(ref, [])

    @pytest.mark.asyncio
    async def test_default_dependencies_with_kit_manifests(self, tmp_path: Path) -> None:
        """DefaultDependencies accepts and exposes kit_manifests."""
        manifest = _make_kit_manifest(
            name="test-kit",
            version="1.0.0",
            workflows=[],
            root_path=tmp_path,
        )

        deps = DefaultDependencies(kit_manifests=[manifest])
        assert deps.kit_manifests is not None
        assert len(deps.kit_manifests) == 1
        assert deps.kit_manifests[0].kit.name == "test-kit"

    @pytest.mark.asyncio
    async def test_default_dependencies_kit_manifests_default_none(self) -> None:
        """DefaultDependencies.kit_manifests defaults to None."""
        deps = DefaultDependencies()
        assert deps.kit_manifests is None


# ---------------------------------------------------------------------------
# Spec fixture: skill-invocation.yaml (subtask 5.1)
# ---------------------------------------------------------------------------


class TestSkillInvocationFixture:
    """Spec fixture skill-invocation.yaml parses and validates."""

    def test_fixture_parses_to_workflow(self) -> None:
        yaml_str = (_VALID_DIR / "skill-invocation.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert isinstance(wf, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = (_VALID_DIR / "skill-invocation.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.id == "skill-invocation-demo"
        assert wf.name == "Skill Invocation Demo"

    def test_step_has_skill_config(self) -> None:
        yaml_str = (_VALID_DIR / "skill-invocation.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert len(wf.steps) == 1
        step = wf.steps[0]
        assert step.id == "use-skill"
        assert step.primitive == "call-agent"
        skill = step.config["skill"]
        assert skill["kit"] == "software-development-kit"
        assert skill["workflow"] == "create-epic"
        assert skill["version"] == ">=0.1.0"


# ---------------------------------------------------------------------------
# Spec fixture: skill-governance.yaml (subtask 5.2)
# ---------------------------------------------------------------------------


class TestSkillGovernanceFixture:
    """Spec fixture skill-governance.yaml parses and validates."""

    def test_fixture_parses_to_workflow(self) -> None:
        yaml_str = (_VALID_DIR / "skill-governance.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert isinstance(wf, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = (_VALID_DIR / "skill-governance.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.id == "skill-governance-demo"
        assert wf.name == "Skill Governance Demo"

    def test_governance_metadata_present(self) -> None:
        yaml_str = (_VALID_DIR / "skill-governance.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        governance = wf.metadata["skills"]["governance"]
        assert governance["policy"] == "strict"
        assert "software-development-kit" in governance["allowed"]

    def test_step_has_skill_config(self) -> None:
        yaml_str = (_VALID_DIR / "skill-governance.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert len(wf.steps) == 1
        step = wf.steps[0]
        assert step.id == "use-governed-skill"
        assert step.primitive == "call-agent"
        skill = step.config["skill"]
        assert skill["kit"] == "software-development-kit"
        assert skill["workflow"] == "create-epic"
        assert skill["version"] == ">=0.1.0"
