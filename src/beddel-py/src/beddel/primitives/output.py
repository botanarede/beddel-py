"""Output-generator primitive — Template-based output extraction."""

from __future__ import annotations

import logging
from typing import Any

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    PrimitiveError,
)

logger = logging.getLogger("beddel.primitives.output")


async def output_primitive(
    config: dict[str, Any],
    context: ExecutionContext,  # noqa: ARG001
) -> Any:
    """Extract and return the resolved template from config.

    The VariableResolver has already substituted all variable references.
    This primitive simply extracts config["template"] and returns it.
    """
    if "template" not in config:
        raise PrimitiveError(
            "output-generator requires a 'template' key in config",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "output-generator", "hint": "Add template field to config"},
        )

    template = config["template"]
    logger.debug("Output template extracted: type=%s", type(template).__name__)
    return template
