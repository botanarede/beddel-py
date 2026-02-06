"""YAML parser — Parse and validate YAML workflow definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from beddel.domain.models import ErrorCode, ParseError, WorkflowDefinition

if TYPE_CHECKING:
    from pathlib import Path


class YAMLParser:
    """Parse YAML workflow files into validated WorkflowDefinition models.

    Uses ``yaml.safe_load`` exclusively for security.
    """

    def parse(self, yaml_content: str) -> WorkflowDefinition:
        """Parse a YAML string into a WorkflowDefinition."""
        raw = self._safe_load(yaml_content)
        return self._validate(raw)

    def parse_file(self, path: Path) -> WorkflowDefinition:
        """Parse a YAML file into a WorkflowDefinition."""
        if not path.exists():
            raise ParseError(
                f"Workflow file not found: {path}",
                code=ErrorCode.PARSE_FILE_NOT_FOUND,
                details={"path": str(path)},
            )
        content = path.read_text(encoding="utf-8")
        return self.parse(content)

    def validate(self, definition: WorkflowDefinition) -> list[str]:
        """Semantic validations beyond Pydantic schema. Returns issues list."""
        issues: list[str] = []
        seen: set[str] = set()

        for step in definition.workflow:
            if step.id in seen:
                issues.append(f"Duplicate step ID: '{step.id}'")
            seen.add(step.id)

        if len(definition.workflow) > definition.config.max_steps:
            issues.append(
                f"Workflow has {len(definition.workflow)} steps, "
                f"exceeding max_steps={definition.config.max_steps}"
            )

        return issues

    def _safe_load(self, content: str) -> dict[str, Any]:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ParseError(
                f"Invalid YAML: {exc}",
                code=ErrorCode.PARSE_INVALID_YAML,
                details={"yaml_error": str(exc)},
            ) from exc

        if not isinstance(data, dict):
            raise ParseError(
                "YAML root must be a mapping",
                code=ErrorCode.PARSE_INVALID_YAML,
                details={"type": type(data).__name__},
            )
        return data

    def _validate(self, raw: dict[str, Any]) -> WorkflowDefinition:
        try:
            return WorkflowDefinition.model_validate(raw)
        except PydanticValidationError as exc:
            raise ParseError(
                f"Workflow validation failed: {exc.error_count()} error(s)",
                code=ErrorCode.PARSE_VALIDATION,
                details={"errors": exc.errors()},
            ) from exc
