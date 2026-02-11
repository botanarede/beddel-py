# 5. Components

## 5.1 Domain Core

**Responsibility:** Pure business logic with zero external dependencies. Defines the workflow execution model, data validation, variable resolution, and primitive contracts.

**Key Interfaces:**
- `WorkflowParser.parse(yaml_str) -> Workflow` — Validates and converts YAML to typed models
- `VariableResolver.resolve(template, context) -> Any` — Resolves `$input`, `$stepResult`, `$env`, and custom namespace references
- `WorkflowExecutor.execute(workflow, inputs) -> dict` — Runs a workflow to completion
- `WorkflowExecutor.execute_stream(workflow, inputs) -> AsyncGenerator[BeddelEvent, None]` — Streaming execution
- `PrimitiveRegistry.get(name) -> IPrimitive` — Looks up a registered primitive by name

**Dependencies:** None (domain core imports nothing from adapters or integrations).

**Technology Stack:** Python 3.11+, Pydantic 2.x, PyYAML 6.x (safe_load only), asyncio.

## 5.2 Compositional Primitives

**Responsibility:** Atomic building blocks that perform specific AI workflow operations. Each primitive implements the `IPrimitive` interface and is registered in the `PrimitiveRegistry`.

**Key Interfaces:**
- `IPrimitive.execute(config, context) -> Any` — Execute the primitive with given config and runtime context
- `@primitive("name")` — Decorator for registration

**Primitives:**

| Primitive | Purpose | Key Dependencies (via metadata) |
|-----------|---------|-------------------------------|
| `llm` | Single-turn LLM invocation | `llm_provider` |
| `chat` | Multi-turn conversation with history | `llm_provider` |
| `output-generator` | Template rendering via VariableResolver | None |
| `call-agent` | Nested workflow invocation | `workflow_loader`, `registry` |
| `guardrail` | Input/output validation | None |
| `tool` | External function invocation | `tool_registry` |

**Dependencies:** Domain core ports only (accessed via `ExecutionContext.metadata`).

## 5.3 Adapters

**Responsibility:** Implement port interfaces for specific external services. Adapters are the only layer that imports third-party libraries.

**Key Interfaces:**
- `LiteLLMAdapter` implements `ILLMProvider` — Multi-provider LLM calls via LiteLLM
- `OpenTelemetryAdapter` implements `ITracer` — Span generation and token tracking
- `LifecycleHookManager` implements `ILifecycleHook` — Event dispatch to registered handlers

**Dependencies:** LiteLLM, opentelemetry-api, httpx.

## 5.4 Integrations

**Responsibility:** Optional framework-specific wiring. Not part of the core SDK — installed via extras.

**Key Interfaces:**
- `create_beddel_handler(workflow, provider?, registry?, hooks?) -> FastAPI route` — Factory for HTTP endpoints
- `BeddelSSEAdapter.stream_events(events) -> AsyncGenerator[SSEEvent, None]` — W3C-compliant SSE serialization

**Dependencies:** FastAPI, sse-starlette (optional extras).

## 5.5 Component Diagrams

```mermaid
graph LR
    subgraph DomainCore["Domain Core"]
        Parser["Parser"]
        Resolver["Resolver"]
        Executor["Executor"]
        Registry["Registry"]
        Models["Models"]
        Ports["Ports"]
    end

    subgraph Prims["Primitives"]
        LLM["llm"]
        Chat["chat"]
        OutGen["output-gen"]
        CallAgent["call-agent"]
        Guard["guardrail"]
        ToolPrim["tool"]
    end

    subgraph Adapt["Adapters"]
        LiteLLM["LiteLLM<br/>Adapter"]
        OTel["OTel<br/>Adapter"]
        Hooks["Lifecycle<br/>Hooks"]
    end

    subgraph Integ["Integrations"]
        FAPI["FastAPI<br/>Handler"]
        SSE["SSE<br/>Adapter"]
    end

    Parser --> Models
    Resolver --> Executor
    Executor --> Registry
    Registry --> Prims
    Prims -.->|via ports| Ports
    Ports -.->|implemented by| Adapt
    FAPI --> Executor
    Executor --> SSE

    style DomainCore fill:#e8f5e9,stroke:#2e7d32
    style Prims fill:#e3f2fd,stroke:#1565c0
    style Adapt fill:#fff3e0,stroke:#e65100
    style Integ fill:#f3e5f5,stroke:#6a1b9a
```

```mermaid
sequenceDiagram
    participant User as User Code
    participant Factory as create_beddel_handler
    participant Executor as WorkflowExecutor
    participant Registry as PrimitiveRegistry
    participant LLMPrim as llm primitive
    participant Adapter as LiteLLMAdapter
    participant Provider as LLM Provider API

    User->>Factory: create_beddel_handler(workflow)
    Factory->>Factory: Auto-create LiteLLMAdapter (if no provider)
    Factory->>Registry: register_builtins()
    Factory->>Executor: WorkflowExecutor(registry, provider, hooks)

    User->>Executor: execute(workflow, inputs)
    Executor->>Executor: Create ExecutionContext (inject provider, hooks)
    loop For each step
        Executor->>Executor: Evaluate if-condition
        Executor->>Registry: get(step.primitive)
        Registry->>LLMPrim: return primitive
        Executor->>LLMPrim: execute(config, context)
        LLMPrim->>LLMPrim: Read context.metadata["llm_provider"]
        LLMPrim->>Adapter: complete(model, messages, ...)
        Adapter->>Adapter: Resolve API key explicitly
        Adapter->>Provider: litellm.acompletion(...)
        Provider-->>Adapter: Response
        Adapter-->>LLMPrim: Result
        LLMPrim-->>Executor: Step result
        Executor->>Executor: Store in context.step_results
    end
    Executor-->>User: Workflow result
```

---
