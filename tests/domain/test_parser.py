"""Unit tests for beddel.domain.parser module."""

from __future__ import annotations

from pathlib import Path

import pytest

from beddel.domain.errors import ParseError
from beddel.domain.models import StrategyType, Workflow
from beddel.domain.parser import WorkflowParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VALID_DIR = _REPO_ROOT / "spec" / "fixtures" / "valid"
_INVALID_DIR = _REPO_ROOT / "spec" / "fixtures" / "invalid"


def _load_fixture(path: Path) -> str:
    """Read a YAML fixture file and return its content as a string."""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Valid workflow parsing
# ---------------------------------------------------------------------------


class TestParseSimpleWorkflow:
    """Tests for parsing the simple.yaml fixture into a Workflow."""

    def test_returns_workflow_instance(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        result = WorkflowParser.parse(yaml_str)

        assert isinstance(result, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert wf.id == "simple-llm"
        assert wf.name == "Simple LLM Workflow"

    def test_workflow_description(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert "minimal workflow" in wf.description.lower()

    def test_input_schema_present(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert wf.input_schema is not None
        assert wf.input_schema["type"] == "object"
        assert "topic" in wf.input_schema["properties"]

    def test_single_step_parsed(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert len(wf.steps) == 1
        assert wf.steps[0].id == "generate"
        assert wf.steps[0].primitive == "llm"

    def test_step_config_preserved(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        wf = WorkflowParser.parse(yaml_str)
        config = wf.steps[0].config

        assert config["model"] == "gpt-4o-mini"
        assert config["temperature"] == 0.7


# ---------------------------------------------------------------------------
# Branching workflow parsing
# ---------------------------------------------------------------------------


class TestParseBranchingWorkflow:
    """Tests for parsing the branching.yaml fixture with if/then/else and strategies."""

    def test_workflow_metadata(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert wf.id == "branching-workflow"
        assert wf.name == "Branching Workflow"
        assert wf.version == "1.1"

    def test_three_top_level_steps(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert len(wf.steps) == 3

    def test_retry_strategy_on_classify_step(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        classify = wf.steps[0]

        assert classify.id == "classify"
        assert classify.execution_strategy.type == StrategyType.RETRY
        assert classify.execution_strategy.retry is not None
        assert classify.execution_strategy.retry.max_attempts == 3
        assert classify.execution_strategy.retry.backoff_base == 1.5
        assert classify.execution_strategy.retry.jitter is True

    def test_classify_step_timeout(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert wf.steps[0].timeout == 30.0

    def test_if_condition_on_route_step(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        route = wf.steps[1]

        assert route.id == "route"
        assert route.if_condition is not None
        assert "$stepResult.classify" in route.if_condition

    def test_then_steps_populated(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        route = wf.steps[1]

        assert route.then_steps is not None
        assert len(route.then_steps) == 1
        assert route.then_steps[0].id == "technical_answer"

    def test_else_steps_populated(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        route = wf.steps[1]

        assert route.else_steps is not None
        assert len(route.else_steps) == 1
        assert route.else_steps[0].id == "general_answer"

    def test_skip_strategy_on_translate_step(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        translate = wf.steps[2]

        assert translate.id == "translate"
        assert translate.execution_strategy.type == StrategyType.SKIP

    def test_translate_step_metadata(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        translate = wf.steps[2]

        assert translate.metadata["optional"] is True
        assert translate.metadata["phase"] == "post-processing"


# ---------------------------------------------------------------------------
# Variable reference preservation (AC 3)
# ---------------------------------------------------------------------------


class TestVariableReferencePreservation:
    """Tests that $input.*, $stepResult.*, $env.* refs are preserved as strings."""

    def test_input_ref_preserved_in_simple(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "simple.yaml")

        wf = WorkflowParser.parse(yaml_str)
        prompt = wf.steps[0].config["prompt"]

        assert "$input.topic" in prompt
        assert isinstance(prompt, str)

    def test_input_ref_preserved_in_branching(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        classify_prompt = wf.steps[0].config["prompt"]

        assert "$input.query" in classify_prompt

    def test_env_ref_preserved_in_translate(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        translate_prompt = wf.steps[2].config["prompt"]

        assert "$env.TRANSLATE_API_KEY" in translate_prompt
        assert "$input.language" in translate_prompt

    def test_step_result_ref_preserved_in_if_condition(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert "$stepResult.classify" in (wf.steps[1].if_condition or "")

    def test_nested_then_step_preserves_input_ref(self) -> None:
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)
        route = wf.steps[1]
        assert route.then_steps is not None
        tech_prompt = route.then_steps[0].config["prompt"]

        assert "$input.query" in tech_prompt

    def test_valid_refs_do_not_trigger_parse_003(self) -> None:
        """Valid variable references must NOT raise BEDDEL-PARSE-003."""
        yaml_str = _load_fixture(_VALID_DIR / "branching.yaml")

        wf = WorkflowParser.parse(yaml_str)

        assert isinstance(wf, Workflow)


# ---------------------------------------------------------------------------
# Invalid YAML syntax → BEDDEL-PARSE-001
# ---------------------------------------------------------------------------


class TestInvalidYamlSyntax:
    """Tests that malformed YAML raises ParseError with BEDDEL-PARSE-001."""

    def test_broken_yaml_syntax(self) -> None:
        bad_yaml = ":\n  :\n  :"

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(bad_yaml)

        assert exc_info.value.code == "BEDDEL-PARSE-001"

    def test_non_mapping_yaml_list(self) -> None:
        list_yaml = "- item1\n- item2"

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(list_yaml)

        assert exc_info.value.code == "BEDDEL-PARSE-001"
        assert "list" in exc_info.value.message.lower()

    def test_non_mapping_yaml_scalar(self) -> None:
        scalar_yaml = "just a string"

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(scalar_yaml)

        assert exc_info.value.code == "BEDDEL-PARSE-001"

    @pytest.mark.parametrize(
        ("label", "yaml_str"),
        [
            ("tab_indentation", "id: test\n\tsteps: []"),
            ("unclosed_quote", 'id: "unclosed'),
        ],
        ids=["tab_indentation", "unclosed_quote"],
    )
    def test_various_syntax_errors(self, label: str, yaml_str: str) -> None:
        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert exc_info.value.code == "BEDDEL-PARSE-001"

    def test_parse_001_has_details(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(":\n  :\n  :")

        assert "source" in exc_info.value.details


# ---------------------------------------------------------------------------
# Schema validation failures → BEDDEL-PARSE-002
# ---------------------------------------------------------------------------


class TestSchemaValidationFailures:
    """Tests that schema violations raise ParseError with BEDDEL-PARSE-002."""

    def test_missing_steps_fixture(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "missing-steps.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert exc_info.value.code == "BEDDEL-PARSE-002"

    def test_bad_strategy_fixture(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "bad-strategy.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert exc_info.value.code == "BEDDEL-PARSE-002"

    def test_parse_002_has_errors_in_details(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "missing-steps.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert "errors" in exc_info.value.details
        assert len(exc_info.value.details["errors"]) >= 1

    def test_parse_002_error_fields_structure(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "missing-steps.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        first_error = exc_info.value.details["errors"][0]
        assert "field" in first_error
        assert "message" in first_error
        assert "type" in first_error

    def test_missing_required_id_inline(self) -> None:
        yaml_str = "name: No ID\nsteps:\n  - id: s1\n    primitive: llm"

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert exc_info.value.code == "BEDDEL-PARSE-002"


# ---------------------------------------------------------------------------
# Invalid variable references → BEDDEL-PARSE-003
# ---------------------------------------------------------------------------


class TestInvalidVariableReferences:
    """Tests that invalid variable refs raise ParseError with BEDDEL-PARSE-003."""

    def test_circular_ref_fixture(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "circular-ref.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert exc_info.value.code == "BEDDEL-PARSE-003"

    def test_parse_003_has_invalid_references_in_details(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "circular-ref.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        refs = exc_info.value.details["invalid_references"]
        assert len(refs) == 2

    def test_parse_003_reference_entries_have_step_and_ref(self) -> None:
        yaml_str = _load_fixture(_INVALID_DIR / "circular-ref.yaml")

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        for entry in exc_info.value.details["invalid_references"]:
            assert "step" in entry
            assert "reference" in entry

    def test_unknown_namespace_detected(self) -> None:
        yaml_str = (
            "id: t\nname: t\nsteps:\n"
            "  - id: s1\n    primitive: llm\n"
            '    config:\n      prompt: "$unknown.foo"'
        )

        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(yaml_str)

        assert exc_info.value.code == "BEDDEL-PARSE-003"
        refs = exc_info.value.details["invalid_references"]
        assert refs[0]["reference"] == "$unknown.foo"


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestParserExports:
    """Tests that __all__ contains expected public names."""

    def test_all_contains_workflow_parser(self) -> None:
        from beddel.domain import parser

        assert "WorkflowParser" in parser.__all__
