# Beddel Python SDK

Agent workflow engine — Python implementation.

## Quick Start

### Installation

```bash
# Core SDK
pip install beddel

# With FastAPI integration
pip install beddel[fastapi]
```

Requires Python 3.11+.

### Minimal Example

```python
from fastapi import FastAPI
from beddel import YAMLParser
from beddel.integrations.fastapi import create_beddel_handler

app = FastAPI()
workflow = YAMLParser().parse_file("workflows/my_workflow.yaml")
handler = create_beddel_handler(workflow)
app.add_api_route("/agent", handler, methods=["POST"], response_model=None)
```

`create_beddel_handler` takes a `WorkflowDefinition` (or a YAML file path) and returns an async HTTP handler. If the workflow contains streaming steps (`stream: true`), the handler automatically returns an SSE stream; otherwise it returns a JSON response.

### Running the Example

The SDK ships with a reference FastAPI app in `examples/`:

```bash
cd src/beddel-py/
uvicorn examples.fastapi_app:app --reload
```

Blocking endpoint (JSON response):

```bash
curl -s -X POST http://localhost:8000/agent/simple \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}' | python -m json.tool
```

Streaming endpoint (SSE):

```bash
curl -N -X POST http://localhost:8000/agent/streaming \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello"}'
```

Health check:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

## API Reference

### `create_beddel_handler`

Factory that creates an async HTTP handler from a workflow definition.

```python
from beddel.integrations.fastapi import create_beddel_handler

handler = create_beddel_handler(
    workflow,                # WorkflowDefinition or str (YAML path)
    provider=None,           # Optional ILLMProvider
    hooks=None,              # Optional list[ILifecycleHook]
    tracer=None,             # Optional ITracer
    registry=None,           # Optional PrimitiveRegistry
)
```

Returns an async callable `(Request) -> JSONResponse | EventSourceResponse`. Automatically selects blocking JSON or SSE streaming based on the workflow's step configuration.

Requires the `beddel[fastapi]` extra.

### `BeddelSSEAdapter`

Framework-agnostic, stateless adapter that converts execution results into SSE events. No dependency on FastAPI or sse-starlette.

```python
from beddel.integrations import BeddelSSEAdapter

adapter = BeddelSSEAdapter()

# From an ExecutionResult:
async for event in adapter.stream(result):
    await response.write(event.serialize().encode())

# From a raw AsyncIterator[str]:
async for event in adapter.stream_iterator(chunks):
    await response.write(event.serialize().encode())
```

Methods:
- `stream(result: ExecutionResult)` — yields `SSEEvent` instances from an execution result. Auto-detects streaming vs. non-streaming output.
- `stream_iterator(iterator: AsyncIterator[str])` — yields `SSEEvent` instances from a raw async string iterator.

### `SSEEvent`

Frozen dataclass representing a single Server-Sent Event.

```python
from beddel.integrations import SSEEvent

event = SSEEvent(event="chunk", data="Hello", id=None, retry=None)
print(event.serialize())
# event: chunk
# data: Hello
```

Fields:
- `event: str` — event type (e.g. `"chunk"`, `"done"`, `"error"`)
- `data: str` — event payload
- `id: str | None` — optional last-event ID for client reconnection
- `retry: int | None` — optional reconnection time in milliseconds

Methods:
- `serialize() -> str` — returns the SSE wire format string per the W3C spec

### `WorkflowDefinition`

Pydantic model representing a complete YAML workflow file.

Fields:
- `metadata: WorkflowMetadata` — name, version, description
- `workflow: list[StepDefinition]` — ordered list of workflow steps
- `config: WorkflowConfig` — global settings (timeout, max steps, environment)
- `return_template: dict | None` — optional output template (aliased as `return` in YAML)

### `ExecutionResult`

Pydantic model representing the result of executing a workflow.

Fields:
- `workflow_id: str` — unique execution identifier
- `success: bool` — whether the workflow completed without errors
- `output: Any` — final workflow output (may be an `AsyncIterator[str]` for streaming)
- `step_results: dict[str, StepResult]` — per-step results keyed by step ID
- `error: str | None` — error message if the workflow failed
- `duration_ms: float` — total execution time in milliseconds

### `WorkflowExecutor`

Executes a `WorkflowDefinition` against a registry of primitives.

```python
from beddel import WorkflowExecutor, PrimitiveRegistry

executor = WorkflowExecutor(
    registry=PrimitiveRegistry(),
    tracer=None,
    hooks=None,
)
result = await executor.execute(workflow_def, {"prompt": "Hello"})
```

### Error Types

All errors extend `BeddelError` which carries a structured `code`, `message`, and `details` dict.

| Error | Description |
|-------|-------------|
| `ParseError` | YAML parsing or Pydantic validation failures |
| `ConfigurationError` | Invalid configuration |
| `ExecutionError` | Workflow execution failures |
| `ProviderError` | LLM provider errors (extends `ExecutionError`) |

## Project Structure

```
src/beddel-py/
├── examples/
│   ├── __init__.py
│   ├── fastapi_app.py          # Reference FastAPI application
│   └── workflows/
│       ├── simple.yaml          # Blocking workflow example
│       └── streaming.yaml       # SSE streaming workflow example
├── src/
│   └── beddel/
│       ├── __init__.py          # Public API re-exports
│       ├── py.typed             # PEP 561 marker
│       ├── adapters/            # External service adapters (LiteLLM, etc.)
│       ├── domain/
│       │   ├── executor.py      # WorkflowExecutor
│       │   ├── models.py        # Pydantic models and error hierarchy
│       │   ├── parser.py        # YAMLParser
│       │   ├── ports.py         # Port interfaces (ILLMProvider, ITracer, etc.)
│       │   ├── registry.py      # PrimitiveRegistry
│       │   └── resolver.py      # VariableResolver
│       ├── integrations/
│       │   ├── __init__.py      # BeddelSSEAdapter, SSEEvent
│       │   ├── fastapi.py       # create_beddel_handler
│       │   └── sse.py           # Framework-agnostic SSE adapter
│       └── primitives/          # Built-in primitive implementations
├── tests/
├── pyproject.toml
└── README.md
```
