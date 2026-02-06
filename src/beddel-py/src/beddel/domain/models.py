"""Domain models — Pydantic models for workflow definitions and execution."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Error Codes
# ---------------------------------------------------------------------------


class ErrorCode(StrEnum):
    """Beddel error codes following BEDDEL-{CATEGORY}-{NUMBER} convention."""

    PARSE_INVALID_YAML = "BEDDEL-PARSE-001"
    PARSE_VALIDATION = "BEDDEL-PARSE-002"
    PARSE_FILE_NOT_FOUND = "BEDDEL-PARSE-003"
    RESOLVE_UNKNOWN_VAR = "BEDDEL-RESOLVE-001"
    RESOLVE_INVALID_PATH = "BEDDEL-RESOLVE-002"
    EXEC_STEP_FAILED = "BEDDEL-EXEC-001"
    EXEC_PRIMITIVE_NOT_FOUND = "BEDDEL-EXEC-002"
    EXEC_TIMEOUT = "BEDDEL-EXEC-003"
    EXEC_CONDITION_FAILED = "BEDDEL-EXEC-004"
    PROVIDER_ERROR = "BEDDEL-PROVIDER-001"
    PROVIDER_TIMEOUT = "BEDDEL-PROVIDER-002"
    CONFIG_INVALID = "BEDDEL-CONFIG-001"


# ---------------------------------------------------------------------------
# Exception Hierarchy
# ---------------------------------------------------------------------------


class BeddelError(Exception):
    """Base exception for all Beddel errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class ParseError(BeddelError):
    """YAML parsing or Pydantic validation errors."""


class ResolutionError(BeddelError):
    """Variable resolution failures."""


class ExecutionError(BeddelError):
    """Workflow execution failures."""


class PrimitiveError(ExecutionError):
    """Primitive-specific execution errors."""


class ProviderError(ExecutionError):
    """LLM provider errors."""


class ConfigurationError(BeddelError):
    """Invalid configuration."""


# ---------------------------------------------------------------------------
# Workflow Definition Models
# ---------------------------------------------------------------------------


class ErrorHandler(BaseModel):
    """Per-step error handling configuration.

    Strategies:
        - ``fail``: Stop workflow on error (default).
        - ``skip``: Log error, mark step as skipped, continue workflow.
    """

    strategy: str = "fail"  # fail | skip


class Message(BaseModel):
    """A single message in a conversation."""

    role: str  # system | user | assistant
    content: str


class StepDefinition(BaseModel):
    """A single step within a workflow."""

    id: str
    type: str  # primitive type: llm, chat, output-generator, etc.
    config: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    condition: str | None = None
    on_error: ErrorHandler | None = None


class WorkflowConfig(BaseModel):
    """Global workflow configuration."""

    timeout_seconds: int = 300
    max_steps: int = 50
    environment: dict[str, str] = Field(default_factory=dict)


class WorkflowMetadata(BaseModel):
    """Workflow metadata block."""

    name: str
    version: str = "1.0.0"
    description: str | None = None


class WorkflowDefinition(BaseModel):
    """Root model representing a complete YAML workflow file."""

    metadata: WorkflowMetadata
    workflow: list[StepDefinition]
    config: WorkflowConfig = Field(default_factory=WorkflowConfig)
    return_template: dict[str, Any] | None = Field(default=None, alias="return")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Execution Models
# ---------------------------------------------------------------------------


class ExecutionContext(BaseModel):
    """Runtime state container for workflow execution."""

    workflow_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    input: dict[str, Any] = Field(default_factory=dict)
    step_results: dict[str, Any] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def with_step_result(self, key: str, result: Any) -> ExecutionContext:
        """Return a new context with an additional step result.

        Args:
            key: The step's ``result`` variable name (used in ``$stepResult.<key>``).
            result: The output value to store.
        """
        new_results = {**self.step_results, key: result}
        return self.model_copy(update={"step_results": new_results})


# ---------------------------------------------------------------------------
# LLM Request / Response Models
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """Token consumption details."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMRequest(BaseModel):
    """Standardized request model for LLM interactions."""

    model: str
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None
    stream: bool = False


class LLMResponse(BaseModel):
    """Standardized response model for LLM interactions."""

    content: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Step Execution Result
# ---------------------------------------------------------------------------


class StepResult(BaseModel):
    """Result of executing a single workflow step."""

    step_id: str
    output: Any = None
    success: bool = True
    error: str | None = None
    duration_ms: float = 0.0


class ExecutionResult(BaseModel):
    """Result of executing a complete workflow."""

    workflow_id: str
    success: bool = True
    output: Any = None
    step_results: dict[str, StepResult] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
