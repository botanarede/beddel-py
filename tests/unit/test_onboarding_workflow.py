"""Tests for the onboarding workflow YAML (Story BC9.4)."""

from __future__ import annotations

import pytest

from beddel.domain.parser import WorkflowParser
from beddel.flows import get_onboarding_workflow_path

_WORKFLOW_PATH = get_onboarding_workflow_path()


class TestOnboardingWorkflowParsing:
    """Verify the onboarding workflow YAML is valid and parseable."""

    @pytest.fixture
    def workflow(self):
        """Load and parse the onboarding workflow."""
        yaml_content = _WORKFLOW_PATH.read_text()
        return WorkflowParser.parse(yaml_content)

    def test_workflow_id(self, workflow) -> None:
        assert workflow.id == "beddel_onboarding"

    def test_workflow_name(self, workflow) -> None:
        assert workflow.name == "Beddel Onboarding"

    def test_step_count(self, workflow) -> None:
        assert len(workflow.steps) == 3

    def test_step_ids(self, workflow) -> None:
        step_ids = [s.id for s in workflow.steps]
        assert step_ids == ["show_form", "generate_config", "show_config"]

    def test_step_primitives(self, workflow) -> None:
        primitives = [s.primitive for s in workflow.steps]
        assert primitives == ["output-generator", "llm", "output-generator"]

    def test_show_form_a2ui_format(self, workflow) -> None:
        show_form = workflow.steps[0]
        assert show_form.config["format"] == "a2ui"

    def test_show_config_a2ui_format(self, workflow) -> None:
        show_config = workflow.steps[2]
        assert show_config.config["format"] == "a2ui"


class TestOnboardingA2UITemplates:
    """Verify A2UI JSON templates are valid."""

    @pytest.fixture
    def workflow(self):
        yaml_content = _WORKFLOW_PATH.read_text()
        return WorkflowParser.parse(yaml_content)

    def test_show_form_template_is_valid_structure(self, workflow) -> None:
        template = workflow.steps[0].config["template"]
        # Template is parsed as a dict from YAML (not a JSON string)
        assert isinstance(template, dict)
        assert "surfaceUpdate" in template

    def test_show_form_has_components(self, workflow) -> None:
        template = workflow.steps[0].config["template"]
        components = template["surfaceUpdate"]["components"]
        assert len(components) >= 3  # At least: title, name input, provider select

    def test_show_config_template_contains_step_result_ref(self, workflow) -> None:
        """The config card template references $stepResult for dynamic content."""
        template = workflow.steps[2].config["template"]
        # Search recursively through dict values for the reference
        template_str = str(template)
        assert "$stepResult.generate_config" in template_str
