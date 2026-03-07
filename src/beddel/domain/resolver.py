"""Variable resolver for the Beddel workflow engine.

Resolves ``$namespace.path`` references in workflow step configurations to
concrete values from the :class:`ExecutionContext`.  Supports built-in
namespaces (``input``, ``stepResult``, ``env``) and custom namespace
registration.

Only stdlib + domain imports are allowed in this module (domain core rule).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from beddel.domain.errors import ResolveError
from beddel.domain.models import ExecutionContext
from beddel.error_codes import RESOLVE_CIRCULAR, RESOLVE_MAX_DEPTH, RESOLVE_UNRESOLVABLE

__all__ = [
    "VariableResolver",
]

# Matches $namespace.path references embedded anywhere in a string.
# Captures (namespace, path) — e.g. "$input.user.name" → ("input", "user.name")
_EMBEDDED_VAR_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_.]*)")


class VariableResolver:
    """Resolves ``$namespace.path`` variable references against an execution context.

    Built-in namespaces:

    - ``$input.<path>`` — traverses ``context.inputs``
    - ``$stepResult.<step_id>.<path>`` — traverses ``context.step_results``
    - ``$env.<VAR>`` — reads from ``os.environ``

    Custom namespaces can be added via :meth:`register_namespace`.

    Resolution is recursive: if a resolved value is itself a string containing
    a ``$namespace.path`` reference, it is resolved again up to *max_depth*
    iterations.  Circular references are detected and reported as
    ``BEDDEL-RESOLVE-002``.

    Args:
        max_depth: Maximum recursion depth for nested variable references.
            Defaults to ``10``.  Exceeding this limit raises
            ``BEDDEL-RESOLVE-003``.
    """

    def __init__(self, *, max_depth: int = 10) -> None:
        self._max_depth = max_depth
        self._handlers: dict[str, Callable[[str, ExecutionContext], Any]] = {
            "input": self._resolve_input,
            "stepResult": self._resolve_step_result,
            "env": self._resolve_env,
        }

    def register_namespace(
        self,
        name: str,
        handler: Callable[[str, ExecutionContext], Any],
    ) -> None:
        """Register a custom namespace handler.

        Args:
            name: Namespace identifier (e.g. ``"secrets"`` for ``$secrets.key``).
            handler: Callable ``(path, context) -> resolved_value``.  Receives
                the dot-separated path after the namespace prefix and the
                current execution context.

        Raises:
            ValueError: If *name* is empty or contains invalid characters.
        """
        if not name or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            msg = f"Invalid namespace name: {name!r}"
            raise ValueError(msg)
        self._handlers[name] = handler

    def resolve(self, template: Any, context: ExecutionContext) -> Any:
        """Resolve all variable references in *template*.

        Recursively walks dicts and lists; delegates string resolution to
        :meth:`_resolve_value`.  Non-string scalars are returned as-is.

        Args:
            template: A value that may contain ``$namespace.path`` references.
                Can be a string, dict, list, or any scalar.
            context: The current execution context providing runtime data.

        Returns:
            The template with all variable references replaced by their
            resolved values.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` when a referenced path
                cannot be found in the context.
            ResolveError: ``BEDDEL-RESOLVE-002`` when a circular variable
                reference is detected.
            ResolveError: ``BEDDEL-RESOLVE-003`` when max recursion depth
                is exceeded.
        """
        if isinstance(template, str):
            return self._resolve_value(template, context)
        if isinstance(template, dict):
            return {k: self.resolve(v, context) for k, v in template.items()}
        if isinstance(template, list):
            return [self.resolve(item, context) for item in template]
        return template

    def _resolve_value(self, value: str, context: ExecutionContext) -> Any:
        """Resolve variable references within a single string.

        Delegates to :meth:`_resolve_recursive` with initial depth and an
        empty resolution chain.

        Args:
            value: A string potentially containing ``$namespace.path`` refs.
            context: The current execution context.

        Returns:
            The resolved value — original type for full-string refs, ``str``
            for embedded refs.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` when a path is unresolvable.
            ResolveError: ``BEDDEL-RESOLVE-002`` when a circular reference
                is detected.
            ResolveError: ``BEDDEL-RESOLVE-003`` when max depth is exceeded.
        """
        return self._resolve_recursive(value, context, depth=0, seen=())

    def _resolve_recursive(
        self,
        value: str,
        context: ExecutionContext,
        *,
        depth: int,
        seen: tuple[str, ...],
    ) -> Any:
        """Resolve variable references with recursion and cycle detection.

        For full-string references (the entire string is one ``$ns.path``),
        the resolved value preserves its native type.  If that value is
        itself a string containing a variable reference, resolution recurses.

        For embedded references (literal text mixed with ``$ns.path``
        tokens), each token is resolved and stringified inline.  The
        resulting plain string does not recurse further.

        Args:
            value: A string potentially containing variable references.
            context: The current execution context.
            depth: Current recursion depth (0-based).
            seen: Ordered tuple of variable paths already visited in this
                resolution chain, used for circular-reference detection.

        Returns:
            The resolved value.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` when a path is unresolvable.
            ResolveError: ``BEDDEL-RESOLVE-002`` when a circular reference
                is detected.
            ResolveError: ``BEDDEL-RESOLVE-003`` when *depth* exceeds
                :attr:`_max_depth`.
        """
        # Fast path: no dollar sign means no variable references.
        if "$" not in value:
            return value

        # Depth guard.
        if depth > self._max_depth:
            raise ResolveError(
                code=RESOLVE_MAX_DEPTH,
                message=(
                    f"Max recursion depth ({self._max_depth}) exceeded "
                    f"while resolving variable '{value}'"
                ),
                details={"variable": value, "max_depth": self._max_depth},
            )

        # Full-string reference: preserve native type and recurse if needed.
        full_match = _EMBEDDED_VAR_RE.fullmatch(value)
        if full_match:
            namespace, path = full_match.group(1), full_match.group(2)
            raw_ref = value  # e.g. "$input.a"

            # Circular reference detection.
            if raw_ref in seen:
                raise ResolveError(
                    code=RESOLVE_CIRCULAR,
                    message=(f"Circular variable reference detected for '{raw_ref}'"),
                    details={
                        "variable": raw_ref,
                        "chain": list(seen) + [raw_ref],
                    },
                )

            resolved = self._dispatch(namespace, path, raw_ref, context)

            # If the resolved value is a string that looks like it contains
            # a variable reference, recurse to resolve it further.
            if isinstance(resolved, str) and "$" in resolved:
                return self._resolve_recursive(
                    resolved,
                    context,
                    depth=depth + 1,
                    seen=(*seen, raw_ref),
                )
            return resolved

        # Embedded references: resolve each match inline, no further recursion.
        # NOTE: Known limitation — embedded refs do NOT recurse.  If a token
        # resolves to a string containing another $var.ref, the nested ref is
        # left as-is.  Full-match refs DO recurse.  This asymmetry is
        # intentional for current use cases (embedded refs typically resolve
        # to terminal values).  Tracked as tech debt for future consideration.
        def _replacer(match: re.Match[str]) -> str:
            namespace, path = match.group(1), match.group(2)
            resolved = self._dispatch(namespace, path, match.group(0), context)
            return str(resolved)

        return _EMBEDDED_VAR_RE.sub(_replacer, value)

    def _dispatch(
        self,
        namespace: str,
        path: str,
        raw_ref: str,
        context: ExecutionContext,
    ) -> Any:
        """Route a variable reference to the appropriate namespace handler.

        Args:
            namespace: The namespace identifier (e.g. ``"input"``).
            path: The dot-separated path within the namespace.
            raw_ref: The original reference string for error messages.
            context: The current execution context.

        Returns:
            The resolved value from the namespace handler.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` if the namespace is unknown.
        """
        handler = self._handlers.get(namespace)
        if handler is None:
            raise ResolveError(
                code=RESOLVE_UNRESOLVABLE,
                message=f"Unknown namespace '{namespace}' in variable '{raw_ref}'",
                details={
                    "variable": raw_ref,
                    "namespace": namespace,
                    "path": path,
                },
            )
        return handler(path, context)

    # ------------------------------------------------------------------
    # Built-in namespace handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_input(path: str, context: ExecutionContext) -> Any:
        """Resolve a path against ``context.inputs``.

        Args:
            path: Dot-separated path (e.g. ``"user.name"``).
            context: The current execution context.

        Returns:
            The value found at the given path.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` if the path is not found.
        """
        return _traverse(context.inputs, path, "input", f"$input.{path}")

    @staticmethod
    def _resolve_step_result(path: str, context: ExecutionContext) -> Any:
        """Resolve a path against ``context.step_results``.

        The first segment of *path* is the step id; remaining segments
        traverse into that step's result value.

        Args:
            path: Dot-separated path where the first segment is a step id
                (e.g. ``"classify.category"``).
            context: The current execution context.

        Returns:
            The value found at the given path.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` if the path is not found.
        """
        return _traverse(context.step_results, path, "stepResult", f"$stepResult.{path}")

    @staticmethod
    def _resolve_env(path: str, context: ExecutionContext) -> Any:
        """Resolve an environment variable name.

        Args:
            path: Environment variable name (e.g. ``"API_KEY"``).
            context: The current execution context (unused but required by
                the handler protocol).

        Returns:
            The value of the environment variable.

        Raises:
            ResolveError: ``BEDDEL-RESOLVE-001`` if the variable is not set.
        """
        # env namespace uses the full path as the variable name (no traversal).
        value = os.environ.get(path)
        if value is None:
            raise ResolveError(
                code=RESOLVE_UNRESOLVABLE,
                message=f"Environment variable '{path}' is not set",
                details={
                    "variable": f"$env.{path}",
                    "namespace": "env",
                    "path": path,
                },
            )
        return value


# ------------------------------------------------------------------
# Shared traversal helper
# ------------------------------------------------------------------


def _traverse(data: dict[str, Any], path: str, namespace: str, raw_ref: str) -> Any:
    """Walk a nested dict using a dot-separated path.

    Args:
        data: The root dict to traverse.
        path: Dot-separated key path (e.g. ``"user.name"``).
        namespace: Namespace name for error context.
        raw_ref: Original variable reference for error messages.

    Returns:
        The value at the end of the path.

    Raises:
        ResolveError: ``BEDDEL-RESOLVE-001`` if any segment is missing.
    """
    segments = path.split(".")
    current: Any = data
    for segment in segments:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            raise ResolveError(
                code=RESOLVE_UNRESOLVABLE,
                message=f"Unresolvable variable '{raw_ref}': key '{segment}' not found",
                details={
                    "variable": raw_ref,
                    "namespace": namespace,
                    "path": path,
                },
            )
    return current
