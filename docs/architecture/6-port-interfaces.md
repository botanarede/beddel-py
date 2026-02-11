# 6. Port Interfaces

All port interfaces live in `domain/ports.py`. The domain core and primitives depend only on these abstractions — never on concrete adapter implementations.

## 6.1 ILLMProvider

```python
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator


class ILLMProvider(ABC):
    """Port interface for LLM provider abstraction."""

    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncGenerator[dict[str, Any], None]:
        """Execute an LLM completion.

        Args:
            model: Model identifier (e.g., "gemini/gemini-2.0-flash").
            messages: Chat messages in OpenAI format.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            stream: If True, returns an async generator of chunks.
            **kwargs: Provider-specific parameters.

        Returns:
            Completion result dict, or async generator of chunk dicts if streaming.

        Raises:
            BeddelError: BEDDEL-ADAPT-001 on authentication failure.
            BeddelError: BEDDEL-ADAPT-002 on provider unavailability.
        """
        ...
```

## 6.2 ILifecycleHook

```python
class ILifecycleHook(ABC):
    """Port interface for lifecycle event handling."""

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None: ...
    async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None: ...
    async def on_step_start(self, step_id: str, primitive: str) -> None: ...
    async def on_step_end(self, step_id: str, result: Any) -> None: ...
    async def on_llm_start(self, model: str, messages: list[dict[str, str]]) -> None: ...
    async def on_llm_end(self, model: str, result: dict[str, Any]) -> None: ...
    async def on_error(self, step_id: str, error: Exception) -> None: ...
    async def on_retry(self, step_id: str, attempt: int, error: Exception) -> None: ...
```

All methods have default no-op implementations. Users override only the hooks they need.

## 6.3 IPrimitive

```python
class IPrimitive(ABC):
    """Port interface for workflow primitives."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Primitive name used for registry lookup."""
        ...

    @abstractmethod
    async def execute(
        self,
        config: dict[str, Any],
        context: "ExecutionContext",
    ) -> Any:
        """Execute the primitive.

        Args:
            config: Step-level configuration from the YAML workflow.
            context: Runtime execution context with inputs, results, and metadata.

        Returns:
            Primitive result (type varies by primitive).

        Raises:
            BeddelError: BEDDEL-PRIM-* on primitive-specific failures.
        """
        ...
```

## 6.4 ITracer

```python
class ITracer(ABC):
    """Port interface for observability tracing."""

    @abstractmethod
    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
        """Start a trace span."""
        ...

    @abstractmethod
    def end_span(self, span: Any, attributes: dict[str, Any] | None = None) -> None:
        """End a trace span with optional final attributes."""
        ...
```

---
