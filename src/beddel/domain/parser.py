"""YAML workflow parser for the Beddel SDK.

Parses YAML workflow definitions into validated :class:`Workflow` domain
models.  Uses ``yaml.safe_load()`` exclusively (NFR7 security requirement)
and validates variable reference syntax without resolving values.

Only stdlib, pydantic, PyYAML, and domain imports are allowed (domain core rule).
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import ValidationError

from beddel.domain.errors import ParseError
from beddel.domain.models import Workflow
from beddel.error_codes import PARSE_INVALID_YAML, PARSE_MALFORMED_VARS, PARSE_SCHEMA_VALIDATION

__all__ = [
    "WorkflowParser",
]

# Matches valid variable references: $input.*, $stepResult.*, $env.*
_VARIABLE_RE = re.compile(r"^\$(?:input|stepResult|env)\.[a-zA-Z_][a-zA-Z0-9_.]*$")


class WorkflowParser:
    """Parses YAML strings into validated ``Workflow`` domain models.

    This parser is stateless — all methods are class-level and carry no
    instance state.  The three-phase pipeline is:

    1. YAML deserialization (``yaml.safe_load``)
    2. Pydantic schema validation
    3. Variable reference syntax validation
    """

    @classmethod
    def parse(cls, yaml_str: str) -> Workflow:
        """Parse a YAML string into a validated ``Workflow``.

        Args:
            yaml_str: Raw YAML content representing a workflow definition.

        Returns:
            A fully validated ``Workflow`` instance.

        Raises:
            ParseError: With code ``BEDDEL-PARSE-001`` for invalid YAML,
                ``BEDDEL-PARSE-002`` for schema validation failures, or
                ``BEDDEL-PARSE-003`` for malformed variable references.
        """
        data = cls._load_yaml(yaml_str)
        workflow = cls._validate_schema(data)
        cls._validate_variable_references(workflow)
        return workflow

    @classmethod
    def _load_yaml(cls, yaml_str: str) -> dict[str, Any]:
        """Deserialize YAML using ``safe_load`` only.

        Args:
            yaml_str: Raw YAML string.

        Returns:
            Parsed dict.

        Raises:
            ParseError: ``BEDDEL-PARSE-001`` on YAML syntax errors.
        """
        try:
            data = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise ParseError(
                code=PARSE_INVALID_YAML,
                message=f"Invalid YAML syntax: {exc}",
                details={"source": str(exc)},
            ) from exc

        if not isinstance(data, dict):
            raise ParseError(
                code=PARSE_INVALID_YAML,
                message=f"YAML document must be a mapping, got {type(data).__name__}",
                details={"type": type(data).__name__},
            )

        return data

    @classmethod
    def _validate_schema(cls, data: dict[str, Any]) -> Workflow:
        """Validate the parsed dict against the ``Workflow`` Pydantic model.

        Args:
            data: Dict produced by ``_load_yaml``.

        Returns:
            Validated ``Workflow`` instance.

        Raises:
            ParseError: ``BEDDEL-PARSE-002`` on Pydantic validation failures.
        """
        try:
            return Workflow.model_validate(data)
        except ValidationError as exc:
            field_errors = [
                {
                    "field": ".".join(str(loc) for loc in err["loc"]),
                    "message": err["msg"],
                    "type": err["type"],
                }
                for err in exc.errors()
            ]
            raise ParseError(
                code=PARSE_SCHEMA_VALIDATION,
                message=f"Workflow schema validation failed with {len(field_errors)} error(s)",
                details={"errors": field_errors},
            ) from exc

    @classmethod
    def _validate_variable_references(cls, workflow: Workflow) -> None:
        """Walk all string values in step configs and validate variable syntax.

        Any string starting with ``$`` must match the pattern
        ``$<namespace>.<path>`` where namespace is one of ``input``,
        ``stepResult``, or ``env``.

        Args:
            workflow: Validated workflow to inspect.

        Raises:
            ParseError: ``BEDDEL-PARSE-003`` for invalid variable references.
        """
        invalid_refs: list[dict[str, str]] = []

        for step in workflow.steps:
            cls._walk_step_configs(step, invalid_refs)

        if invalid_refs:
            raise ParseError(
                code=PARSE_MALFORMED_VARS,
                message=f"Invalid variable reference(s): {len(invalid_refs)} found",
                details={"invalid_references": invalid_refs},
            )

    @classmethod
    def _walk_step_configs(
        cls,
        step: Any,
        invalid_refs: list[dict[str, str]],
    ) -> None:
        """Recursively walk a step and its nested steps for variable refs.

        Args:
            step: A ``Step`` instance to inspect.
            invalid_refs: Accumulator for invalid references found.
        """
        cls._check_strings(step.config, step.id, invalid_refs)

        if step.then_steps:
            for child in step.then_steps:
                cls._walk_step_configs(child, invalid_refs)
        if step.else_steps:
            for child in step.else_steps:
                cls._walk_step_configs(child, invalid_refs)

    @classmethod
    def _check_strings(
        cls,
        value: Any,
        step_id: str,
        invalid_refs: list[dict[str, str]],
    ) -> None:
        """Recursively check string values for valid variable references.

        Args:
            value: Any value from a config dict to inspect.
            step_id: Owning step id for error context.
            invalid_refs: Accumulator for invalid references found.
        """
        if isinstance(value, str):
            if value.startswith("$") and not _VARIABLE_RE.match(value):
                invalid_refs.append({"step": step_id, "reference": value})
        elif isinstance(value, dict):
            for v in value.values():
                cls._check_strings(v, step_id, invalid_refs)
        elif isinstance(value, list):
            for item in value:
                cls._check_strings(item, step_id, invalid_refs)
