# 7. Epic 3: Observability & Integration

**Goal:** Add production-grade observability and framework integration so developers can deploy, monitor, and stream workflows in real applications.

## Story 3.1: OpenTelemetry Tracing

As a platform engineer,
I want workflow execution to emit OpenTelemetry traces,
so that I can monitor performance, debug issues, and track LLM token usage across providers.

**Acceptance Criteria:**
1. Spans generated for workflow execution, step execution, and primitive invocation
2. Token usage tracked per step and per workflow as span attributes
3. Custom attributes include model, provider, and execution strategy
4. Tracing is opt-in and does not affect performance when disabled

## Story 3.2: Lifecycle Hooks

As a developer,
I want to hook into workflow execution events,
so that I can add custom logging, metrics, or side effects at any point in the execution lifecycle.

**Acceptance Criteria:**
1. Events supported: `on_workflow_start`, `on_workflow_end`, `on_step_start`, `on_step_end`, `on_llm_start`, `on_llm_end`, `on_error`, `on_retry`
2. User-registerable hook handlers
3. Hook dispatch uses a single unified mechanism — no dual-channel mismatch between executor hooks and metadata hooks
4. Hooks are injected into ExecutionContext metadata by the executor

## Story 3.3: FastAPI Handler & SSE Streaming

As a developer,
I want to expose my workflows as HTTP endpoints with real-time streaming,
so that I can integrate Beddel into web applications.

**Acceptance Criteria:**
1. `create_beddel_handler()` factory creates FastAPI route handlers from workflow definitions
2. Available as optional extra: `pip install beddel[fastapi]`
3. Default provider (`LiteLLMAdapter()`) and default registry (with `register_builtins()`) when none supplied
4. SSE streaming via `execute_stream()` piped through `BeddelSSEAdapter.stream_events()`
5. SSE serialization correctly handles multi-line data per W3C SSE specification (each line as separate `data:` field)
6. All cross-module utility functions use public naming (no underscore prefix for imported functions)

---
