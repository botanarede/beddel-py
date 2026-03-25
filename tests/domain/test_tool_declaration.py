"""Unit tests for ToolDeclaration model and inline YAML tools parsing."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from beddel.domain.errors import ParseError
from beddel.domain.models import ToolDeclaration, Workflow
from beddel.domain.parser import WorkflowParser

# ---------------------------------------------------------------------------
# ToolDeclaration model validation
# ---------------------------------------------------------------------------


class TestToolDeclarationModel:
    """Tests for the ToolDeclaration Pydantic model."""

    def test_valid_tool_declaration(self) -> None:
        td = ToolDeclaration(name="my_tool", target="json:dumps")
        assert td.name == "my_tool"
        assert td.target == "json:dumps"

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            ToolDeclaration(target="json:dumps")  # type: ignore[call-arg]

    def test_missing_target_raises(self) -> None:
        with pytest.raises(ValidationError):
            ToolDeclaration(name="my_tool")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Workflow model with tools field
# ---------------------------------------------------------------------------


class TestWorkflowToolsField:
    """Tests for the optional tools field on Workflow."""

    def test_workflow_without_tools_defaults_none(self) -> None:
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
        )
        assert wf.tools is None

    def test_workflow_with_tools_list(self) -> None:
        wf = Workflow(
            id="t",
            name="t",
            steps=[{"id": "s1", "primitive": "llm"}],  # type: ignore[list-item]
            tools=[ToolDeclaration(name="dumper", target="json:dumps")],
        )
        assert wf.tools is not None
        assert len(wf.tools) == 1
        assert wf.tools[0].name == "dumper"


# ---------------------------------------------------------------------------
# Parser inline tool resolution
# ---------------------------------------------------------------------------

_MINIMAL_YAML = """\
id: t
name: t
steps:
  - id: s1
    primitive: llm
"""

_YAML_WITH_TOOLS = """\
id: t
name: t
steps:
  - id: s1
    primitive: llm
tools:
  - name: dumper
    target: "json:dumps"
"""

_YAML_WITH_BAD_MODULE = """\
id: t
name: t
steps:
  - id: s1
    primitive: llm
tools:
  - name: bad
    target: "nonexistent_module_xyz:func"
"""

_YAML_WITH_BAD_ATTR = """\
id: t
name: t
steps:
  - id: s1
    primitive: llm
tools:
  - name: bad
    target: "json:nonexistent_attr_xyz"
"""

_YAML_WITH_NON_CALLABLE = """\
id: t
name: t
steps:
  - id: s1
    primitive: llm
tools:
  - name: bad
    target: "json:__name__"
"""

_YAML_WITH_DUPLICATE_TOOLS = """\
id: t
name: t
steps:
  - id: s1
    primitive: llm
tools:
  - name: dumper
    target: "json:dumps"
  - name: dumper
    target: "json:loads"
"""


class TestParserInlineToolResolution:
    """Tests for WorkflowParser resolving inline tools at parse time."""

    def test_no_tools_section_works(self) -> None:
        wf = WorkflowParser.parse(_MINIMAL_YAML)
        assert wf.tools is None
        assert "_inline_tools" not in wf.metadata

    def test_resolves_valid_tool(self) -> None:
        wf = WorkflowParser.parse(_YAML_WITH_TOOLS)
        assert "_inline_tools" in wf.metadata
        resolved = wf.metadata["_inline_tools"]
        assert "dumper" in resolved
        assert resolved["dumper"] is json.dumps

    def test_raises_parse_error_on_bad_module(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(_YAML_WITH_BAD_MODULE)
        assert exc_info.value.code == "BEDDEL-PARSE-002"

    def test_raises_parse_error_on_bad_attr(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(_YAML_WITH_BAD_ATTR)
        assert exc_info.value.code == "BEDDEL-PARSE-002"

    def test_raises_parse_error_on_non_callable(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(_YAML_WITH_NON_CALLABLE)
        assert exc_info.value.code == "BEDDEL-PARSE-002"

    def test_stores_resolved_in_metadata(self) -> None:
        wf = WorkflowParser.parse(_YAML_WITH_TOOLS)
        assert isinstance(wf.metadata["_inline_tools"], dict)
        assert callable(wf.metadata["_inline_tools"]["dumper"])

    def test_raises_parse_error_on_duplicate_tool_name(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            WorkflowParser.parse(_YAML_WITH_DUPLICATE_TOOLS)
        assert exc_info.value.code == "BEDDEL-PARSE-004"
        assert "Duplicate tool name" in exc_info.value.message
        assert exc_info.value.details["tool"] == "dumper"
