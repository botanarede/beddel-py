"""Guardrail primitive — input/output validation for Beddel workflows.

Provides :class:`GuardrailPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and validates data against
dynamically-built Pydantic models with four configurable failure strategies:
``raise``, ``return_errors``, ``correct``, and ``delegate``.

The ``correct`` strategy attempts JSON repair for malformed LLM responses
(parse → strip markdown fences → retry).  The ``delegate`` strategy calls
an LLM provider to fix validation errors, retrying up to ``max_attempts``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError, create_model

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider, IPrimitive
from beddel.error_codes import (
    GUARD_INVALID_STRATEGY,
    GUARD_MISSING_CONFIG,
    GUARD_VALIDATION_FAILED,
)
from beddel.primitives._llm_utils import get_provider

__all__ = [
    "GuardrailPrimitive",
]

_VALID_STRATEGIES = frozenset({"raise", "return_errors", "correct", "delegate"})

_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}

_FENCE_OPEN = re.compile(r"^```(?:json)?\s*\n?", flags=re.MULTILINE)
_FENCE_CLOSE = re.compile(r"\n?```\s*$", flags=re.MULTILINE)


class GuardrailPrimitive(IPrimitive):
    """Data validation primitive with configurable failure strategies.

    Validates data against a schema defined as a dict of field descriptors,
    building a dynamic Pydantic model at runtime.  When validation fails,
    the configured strategy determines the recovery behaviour.

    Config keys:
        data (Any): Required. The data to validate.
        schema (dict): Required. Validation schema with a ``"fields"`` key
            mapping field names to type descriptors.
        strategy (str): Optional. Failure strategy — ``"raise"``,
            ``"return_errors"``, ``"correct"``, or ``"delegate"``
            (default: ``"raise"``).
        max_attempts (int): Optional. Retry limit for ``"delegate"``
            strategy (default: ``1``).
        model (str): Optional. LLM model name for ``"delegate"`` strategy.

    Schema format example::

        {
            "fields": {
                "name": {"type": "str", "required": True},
                "age": {"type": "int"},
            }
        }

    Strategy behaviours:

    =========== ============================================ ============
    Strategy    On Validation Failure                        LLM Required
    =========== ============================================ ============
    raise       Raises ``PrimitiveError("BEDDEL-GUARD-201")`` No
    return_errors Returns error dict with ``valid: False``   No
    correct     JSON repair → re-validate → fall back        No
    delegate    LLM correction → re-validate → fall back     Yes
    =========== ============================================ ============
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the guardrail primitive.

        Validates ``data`` against ``schema`` and dispatches to the
        configured failure strategy when validation errors are found.

        Args:
            config: Primitive configuration containing ``data`` and
                ``schema`` (required), plus optional ``strategy``,
                ``max_attempts``, and ``model`` keys.
            context: Execution context providing runtime dependencies.

        Returns:
            A dict with ``"valid"`` (bool) and ``"data"`` keys, plus
            ``"errors"`` when validation fails (for non-raise strategies).

        Raises:
            PrimitiveError: ``BEDDEL-GUARD-203`` when required config keys
                (``data``, ``schema``) are missing.
            PrimitiveError: ``BEDDEL-GUARD-201`` when strategy is ``"raise"``
                and validation fails.
            PrimitiveError: ``BEDDEL-GUARD-202`` when an invalid strategy
                is specified.
            PrimitiveError: ``BEDDEL-PRIM-003`` when ``"delegate"`` strategy
                is used without an ``llm_provider`` in context deps.
        """
        self._validate_config(config, context)

        data = config["data"]
        schema = config["schema"]
        strategy = config.get("strategy", "raise")

        is_valid, errors = self._validate(data, schema)
        if is_valid:
            return {"valid": True, "data": data}

        if strategy == "raise":
            return self._strategy_raise(errors, context)
        if strategy == "return_errors":
            return self._strategy_return_errors(data, errors)
        if strategy == "correct":
            return self._strategy_correct(data, schema, errors)
        # strategy == "delegate"
        return await self._strategy_delegate(data, errors, config, context)

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> None:
        """Validate required config keys and strategy value.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-GUARD-203`` if required keys are missing.
            PrimitiveError: ``BEDDEL-GUARD-202`` if strategy is invalid.
        """
        for key in ("data", "schema"):
            if key not in config:
                raise PrimitiveError(
                    code=GUARD_MISSING_CONFIG,
                    message=f"Missing required config key '{key}' for guardrail",
                    details={
                        "primitive": "guardrail",
                        "step_id": context.current_step_id,
                        "missing_key": key,
                    },
                )

        strategy = config.get("strategy", "raise")
        if strategy not in _VALID_STRATEGIES:
            raise PrimitiveError(
                code=GUARD_INVALID_STRATEGY,
                message=(
                    f"Invalid guardrail strategy '{strategy}'. "
                    f"Supported: {', '.join(sorted(_VALID_STRATEGIES))}"
                ),
                details={
                    "primitive": "guardrail",
                    "step_id": context.current_step_id,
                    "strategy": strategy,
                },
            )

    @staticmethod
    def _validate(data: Any, schema: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate data against a schema by building a dynamic Pydantic model.

        Constructs field definitions from the schema's ``"fields"`` dict,
        maps type strings to Python types, and runs Pydantic validation.

        Args:
            data: The data to validate. Must be a dict for field-level
                validation.
            schema: Schema dict containing a ``"fields"`` key with field
                descriptors.

        Returns:
            A ``(is_valid, errors)`` tuple where ``is_valid`` is ``True``
            when data passes validation, and ``errors`` is a list of
            human-readable error strings (empty when valid).
        """
        fields_spec = schema.get("fields", {})
        if not fields_spec:
            return True, []

        field_definitions: dict[str, Any] = {}
        for field_name, field_desc in fields_spec.items():
            field_type = _TYPE_MAP.get(field_desc.get("type", "str"), str)
            is_required = field_desc.get("required", False)

            if is_required:
                field_definitions[field_name] = (field_type, ...)
            else:
                field_definitions[field_name] = (field_type, None)

        dynamic_model = create_model("GuardrailModel", **field_definitions)

        if not isinstance(data, dict):
            return False, [f"Expected dict, got {type(data).__name__}"]

        try:
            dynamic_model.model_validate(data)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
            ]
            return False, errors

        return True, []

    @staticmethod
    def _strategy_raise(errors: list[str], context: ExecutionContext) -> Any:
        """Raise a PrimitiveError with validation errors.

        Args:
            errors: List of validation error messages.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-GUARD-201`` always.
        """
        raise PrimitiveError(
            code=GUARD_VALIDATION_FAILED,
            message="Guardrail validation failed",
            details={
                "primitive": "guardrail",
                "step_id": context.current_step_id,
                "errors": errors,
            },
        )

    @staticmethod
    def _strategy_return_errors(data: Any, errors: list[str]) -> dict[str, Any]:
        """Return a dict containing validation errors without raising.

        Args:
            data: The original data that failed validation.
            errors: List of validation error messages.

        Returns:
            Dict with ``valid: False``, the error list, and original data.
        """
        return {"valid": False, "errors": errors, "data": data}

    @staticmethod
    def _strategy_correct(
        data: Any,
        schema: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Attempt JSON repair on string data and re-validate.

        Repair algorithm:
        1. If ``data`` is a string, try ``json.loads(data)`` → validate.
        2. If that fails, strip markdown code fences → retry parse → validate.
        3. If still invalid, fall back to ``return_errors`` behaviour.

        Args:
            data: The data to attempt repair on (typically a string).
            schema: The validation schema to re-validate against.
            errors: Original validation errors (used in fallback).

        Returns:
            Dict with ``valid: True`` and corrected data on success, or
            ``valid: False`` with errors on failure.
        """
        if not isinstance(data, str):
            return {"valid": False, "errors": errors, "data": data}

        # Step 1: try direct JSON parse
        parsed = _try_json_parse(data)
        if parsed is not None:
            is_valid, new_errors = GuardrailPrimitive._validate(parsed, schema)
            if is_valid:
                return {"valid": True, "data": parsed}
            errors = new_errors

        # Step 2: strip markdown fences and retry
        stripped = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", data))
        if stripped != data:
            parsed = _try_json_parse(stripped)
            if parsed is not None:
                is_valid, new_errors = GuardrailPrimitive._validate(parsed, schema)
                if is_valid:
                    return {"valid": True, "data": parsed}
                errors = new_errors

        # Step 3: fall back to return_errors
        return {"valid": False, "errors": errors, "data": data}

    @staticmethod
    def _get_provider(context: ExecutionContext) -> ILLMProvider:
        """Extract and validate the LLM provider from context deps.

        Args:
            context: Execution context providing runtime dependencies.

        Returns:
            The LLM provider instance.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-003`` if ``llm_provider`` is
                missing from context deps.
        """
        return get_provider(context, "guardrail")

    @staticmethod
    async def _strategy_delegate(
        data: Any,
        errors: list[str],
        config: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Delegate correction to an LLM provider and re-validate.

        Sends the validation errors and original data to the LLM, asking
        it to produce corrected JSON.  Retries up to ``max_attempts``.

        Args:
            data: The data that failed validation.
            errors: List of validation error messages.
            config: Primitive config containing ``schema``, optional
                ``model`` and ``max_attempts``.
            context: Execution context providing the LLM provider.

        Returns:
            Dict with ``valid: True`` and corrected data on success, or
            ``valid: False`` with errors after exhausting attempts.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-003`` if ``llm_provider`` is
                missing from context deps.
        """
        provider = GuardrailPrimitive._get_provider(context)
        schema = config["schema"]
        model = config.get("model", context.deps.delegate_model)
        max_attempts = config.get("max_attempts", 1)

        last_errors = errors
        last_data = data

        for _attempt in range(max_attempts):
            prompt = (
                f"Fix this data to match the schema: {json.dumps(schema)}. "
                f"Errors: {json.dumps(last_errors)}. "
                f"Data: {json.dumps(last_data) if not isinstance(last_data, str) else last_data}\n"
                "Respond with ONLY the corrected JSON, no explanation."
            )
            messages = [{"role": "user", "content": prompt}]
            response = await provider.complete(model, messages)
            content = response.get("content", "")

            parsed = _try_json_parse(content)
            if parsed is None:
                # Try stripping markdown fences
                stripped = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", content))
                parsed = _try_json_parse(stripped)

            if parsed is not None:
                is_valid, new_errors = GuardrailPrimitive._validate(parsed, schema)
                if is_valid:
                    return {"valid": True, "data": parsed}
                last_errors = new_errors
                last_data = parsed
            else:
                last_errors = [f"LLM response is not valid JSON: {content[:200]}"]
                last_data = content

        return {"valid": False, "errors": last_errors, "data": last_data}


def _try_json_parse(text: str) -> Any | None:
    """Attempt to parse a string as JSON, returning None on failure.

    Args:
        text: The string to parse.

    Returns:
        The parsed value, or ``None`` if parsing fails.
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
