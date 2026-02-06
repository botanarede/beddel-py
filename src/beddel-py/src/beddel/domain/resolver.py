"""Variable resolver — Resolve $input.*, $stepResult.*, $env.* references."""

from __future__ import annotations

import os
import re
from typing import Any

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    ResolutionError,
)

# Pattern matches $input.foo, $stepResult.bar.baz, $env.API_KEY
_VAR_PATTERN = re.compile(r"\$(?P<namespace>input|stepResult|env)\.(?P<path>[a-zA-Z0-9_.]+)")


class VariableResolver:
    """Resolve variable references recursively in templates.

    Supported namespaces:
        - ``$input.*``       — from ``context.input``
        - ``$stepResult.*``  — from ``context.step_results``
        - ``$env.*``         — from ``context.env`` (falls back to ``os.environ``)
    """

    def resolve(self, template: Any, context: ExecutionContext) -> Any:
        """Resolve a single value — string, dict, list, or passthrough."""
        if isinstance(template, str):
            return self._resolve_string(template, context)
        if isinstance(template, dict):
            return self.resolve_dict(template, context)
        if isinstance(template, list):
            return [self.resolve(item, context) for item in template]
        # int, float, bool, None — passthrough
        return template

    def resolve_dict(self, data: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        """Resolve all variable references in a dict recursively."""
        return {key: self.resolve(value, context) for key, value in data.items()}

    # -- private helpers --

    def _resolve_string(self, template: str, context: ExecutionContext) -> Any:
        """Resolve variable references in a string.

        If the entire string is a single variable reference, return the raw
        resolved value (preserving type). Otherwise, substitute inline.
        """
        # Full-string match: return raw value (preserves dicts, lists, etc.)
        full_match = _VAR_PATTERN.fullmatch(template)
        if full_match:
            return self._lookup(
                full_match.group("namespace"),
                full_match.group("path"),
                context,
            )

        # Inline substitution: convert resolved values to strings
        def _replacer(match: re.Match[str]) -> str:
            value = self._lookup(match.group("namespace"), match.group("path"), context)
            return str(value)

        return _VAR_PATTERN.sub(_replacer, template)

    def _lookup(self, namespace: str, path: str, context: ExecutionContext) -> Any:
        """Look up a variable by namespace and dotted path."""
        if namespace == "input":
            return self._traverse(context.input, path, namespace)
        if namespace == "stepResult":
            return self._traverse(context.step_results, path, namespace)
        if namespace == "env":
            # Single-segment env lookup
            key = path
            value = context.env.get(key) or os.environ.get(key)
            if value is None:
                raise ResolutionError(
                    f"Environment variable '{key}' not found",
                    code=ErrorCode.RESOLVE_UNKNOWN_VAR,
                    details={"namespace": namespace, "key": key},
                )
            return value

        raise ResolutionError(
            f"Unknown namespace: '{namespace}'",
            code=ErrorCode.RESOLVE_UNKNOWN_VAR,
            details={"namespace": namespace, "path": path},
        )

    def _traverse(self, data: Any, path: str, namespace: str) -> Any:
        """Walk a dotted path through nested dicts."""
        segments = path.split(".")
        current = data
        for i, segment in enumerate(segments):
            if isinstance(current, dict):
                if segment not in current:
                    traversed = ".".join(segments[: i + 1])
                    raise ResolutionError(
                        f"Key '{segment}' not found in ${namespace}.{traversed}",
                        code=ErrorCode.RESOLVE_INVALID_PATH,
                        details={
                            "namespace": namespace,
                            "path": path,
                            "missing_segment": segment,
                            "available_keys": (
                                list(current.keys()) if isinstance(current, dict) else []
                            ),
                        },
                    )
                current = current[segment]
            else:
                traversed = ".".join(segments[:i])
                raise ResolutionError(
                    f"Cannot traverse into non-dict at ${namespace}.{traversed}",
                    code=ErrorCode.RESOLVE_INVALID_PATH,
                    details={"namespace": namespace, "path": path, "type": type(current).__name__},
                )
        return current
