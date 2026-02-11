# 4. Data Models

## 4.1 Workflow

**Purpose:** Top-level container for a declarative AI workflow definition. Parsed from YAML and validated by Pydantic.

```python
class Workflow(BaseModel):
    """Top-level workflow definition."""
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    input_schema: dict[str, Any] | None = None
    steps: list[Step]
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**Relationships:** Contains one or more `Step` instances. Referenced by `WorkflowExecutor` for execution.

## 4.2 Step

**Purpose:** A single unit of work within a workflow. References a primitive by name and declares execution behavior.

```python
class Step(BaseModel):
    """Single workflow step definition."""
    id: str
    primitive: str                                    # Registry lookup key
    config: dict[str, Any] = Field(default_factory=dict)
    if_condition: str | None = Field(None, alias="if")
    then_steps: list[Step] | None = Field(None, alias="then")
    else_steps: list[Step] | None = Field(None, alias="else")
    execution_strategy: ExecutionStrategy = Field(
        default_factory=lambda: ExecutionStrategy(type=StrategyType.FAIL)
    )
    timeout: float | None = None                      # Seconds
    stream: bool = False
    parallel: bool = False                            # Reserved for Epic 4
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**Relationships:** Belongs to a `Workflow`. May contain nested `then`/`else` sub-steps. References a primitive by name via the `PrimitiveRegistry`.

## 4.3 ExecutionStrategy

**Purpose:** Declares how errors are handled for a specific step. Supports graduated strategies (NFR16).

```python
class StrategyType(str, Enum):
    FAIL = "fail"
    SKIP = "skip"
    RETRY = "retry"
    FALLBACK = "fallback"
    DELEGATE = "delegate"  # Epic 4+

class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_base: float = 2.0       # Exponential backoff base (seconds)
    backoff_max: float = 60.0       # Maximum backoff delay
    jitter: bool = True             # Add random jitter to prevent thundering herd

class ExecutionStrategy(BaseModel):
    type: StrategyType = StrategyType.FAIL
    retry: RetryConfig | None = None
    fallback_step: Step | None = None
```

## 4.4 ExecutionContext

**Purpose:** Runtime state container passed to every primitive during execution. Carries inputs, step results, resolved variables, and injected dependencies via `metadata`.

```python
class ExecutionContext(BaseModel):
    """Runtime execution state passed to primitives."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    step_results: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    current_step_id: str | None = None
```

**Relationships:** Created by `WorkflowExecutor` at execution start. Passed to every `IPrimitive.execute()` call. Updated with step results after each step completes.

## 4.5 BeddelEvent

**Purpose:** Structured event emitted during streaming execution. Used by `execute_stream()`, lifecycle hooks, and the SSE adapter.

```python
class EventType(str, Enum):
    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    STEP_START = "step_start"
    STEP_END = "step_end"
    LLM_START = "llm_start"
    LLM_END = "llm_end"
    TEXT_CHUNK = "text_chunk"
    ERROR = "error"
    RETRY = "retry"

class BeddelEvent(BaseModel):
    """Structured event for streaming and observability."""
    event_type: EventType
    step_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
```

**Relationships:** Yielded by `WorkflowExecutor.execute_stream()`. Consumed by `BeddelSSEAdapter` for HTTP streaming. Dispatched to `ILifecycleHook` handlers.

## 4.6 BeddelError

**Purpose:** Structured error with `BEDDEL-` prefixed error codes (NFR15).

```python
class BeddelError(Exception):
    """Base error with structured error code."""
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code          # e.g., "BEDDEL-EXEC-001"
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")
```

**Domain error codes:**

| Prefix | Domain | Examples |
|--------|--------|----------|
| `BEDDEL-PARSE-` | YAML parsing & validation | `BEDDEL-PARSE-001`: Invalid YAML syntax |
| `BEDDEL-RESOLVE-` | Variable resolution | `BEDDEL-RESOLVE-001`: Unresolvable variable |
| `BEDDEL-EXEC-` | Workflow execution | `BEDDEL-EXEC-001`: Missing metadata key |
| `BEDDEL-PRIM-` | Primitive execution | `BEDDEL-PRIM-001`: Primitive not found |
| `BEDDEL-ADAPT-` | Adapter errors | `BEDDEL-ADAPT-001`: Provider authentication failure |

---
