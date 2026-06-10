"""Tests for the setup workflow YAML structure (formerly onboarding)."""

from __future__ import annotations

import pytest

from beddel.domain.parser import WorkflowParser
from beddel.flows import get_bundled_workflow_path

_WORKFLOW_PATH = get_bundled_workflow_path("setup")


class TestSetupWorkflowParsing:
    """Verify the setup workflow YAML is valid and parseable."""

    @pytest.fixture()
    def workflow(self):
        """Load and parse the setup workflow."""
        yaml_content = _WORKFLOW_PATH.read_text()
        return WorkflowParser.parse(yaml_content)

    def test_workflow_id(self, workflow) -> None:
        assert workflow.id == "beddel_setup"

    def test_workflow_name(self, workflow) -> None:
        assert workflow.name == "Beddel Setup"

    def test_step_count(self, workflow) -> None:
        assert len(workflow.steps) == 4

    def test_step_ids(self, workflow) -> None:
        step_ids = [s.id for s in workflow.steps]
        assert step_ids == [
            "load_state",
            "show_form",
            "save",
            "show_done",
        ]

    def test_step_primitives(self, workflow) -> None:
        primitives = [s.primitive for s in workflow.steps]
        assert primitives == [
            "tool",
            "output-generator",
            "tool",
            "output-generator",
        ]

    def test_gated_steps(self, workflow) -> None:
        """save and show_done are gated on generate==true."""
        by_id = {s.id: s for s in workflow.steps}
        assert by_id["load_state"].if_condition is None
        assert by_id["show_form"].if_condition is None
        assert by_id["save"].if_condition == "$input.generate == true"
        assert by_id["show_done"].if_condition == "$input.generate == true"

    def test_load_state_uses_load_setup_tool(self, workflow) -> None:
        """The load_state step invokes load_setup from the tools section."""
        load_step = next(s for s in workflow.steps if s.id == "load_state")
        assert load_step.config["tool"] == "load_setup"
        assert workflow.metadata["_inline_tools"]["load_setup"] is not None

    def test_save_uses_save_setup_tool(self, workflow) -> None:
        """The save step invokes save_setup from the tools section."""
        save_step = next(s for s in workflow.steps if s.id == "save")
        assert save_step.config["tool"] == "save_setup"
        assert workflow.metadata["_inline_tools"]["save_setup"] is not None

    def test_show_form_a2ui_format(self, workflow) -> None:
        show_form = next(s for s in workflow.steps if s.id == "show_form")
        assert show_form.config["format"] == "a2ui"


class TestSetupA2UITemplates:
    """Verify A2UI JSON templates are valid."""

    @pytest.fixture()
    def workflow(self):
        yaml_content = _WORKFLOW_PATH.read_text()
        return WorkflowParser.parse(yaml_content)

    def test_show_form_template_is_valid_structure(self, workflow) -> None:
        show_form = next(s for s in workflow.steps if s.id == "show_form")
        template = show_form.config["template"]
        assert isinstance(template, dict)
        assert "surfaceUpdate" in template

    def test_show_form_has_components(self, workflow) -> None:
        show_form = next(s for s in workflow.steps if s.id == "show_form")
        template = show_form.config["template"]
        components = template["surfaceUpdate"]["components"]
        assert len(components) >= 5  # title, headers, inputs, select, button

    def test_show_form_components_reference_step_result(self, workflow) -> None:
        """Form components reference $stepResult.load_state.result for pre-population."""
        show_form = next(s for s in workflow.steps if s.id == "show_form")
        template = show_form.config["template"]
        template_str = str(template)
        assert "$stepResult.load_state.result" in template_str
