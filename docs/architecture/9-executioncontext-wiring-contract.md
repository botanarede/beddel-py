# 9. ExecutionContext Wiring Contract

> **NFR18 / Lesson §13.5** — This table is the single source of truth for all metadata keys in `ExecutionContext.metadata`. Every key documents which primitive requires it, who provides it, and what happens when it's absent.

| Metadata Key | Type | Required By | Provided By | Error When Absent |
|-------------|------|-------------|-------------|-------------------|
| `llm_provider` | `ILLMProvider` | `llm`, `chat` | `WorkflowExecutor.__init__` (injected in `execute()`/`execute_stream()`) | `BEDDEL-EXEC-001: llm_provider not found in execution context metadata` |
| `lifecycle_hooks` | `list[ILifecycleHook]` | Executor (internal), `llm` (for `on_llm_start`/`on_llm_end`) | `WorkflowExecutor.__init__` (injected in `execute()`/`execute_stream()`) | Silent no-op (hooks are optional) |
| `workflow_loader` | `Callable[[str], Workflow]` | `call-agent` | User or handler factory | `BEDDEL-PRIM-001: workflow_loader not found in execution context metadata` |
| `registry` | `PrimitiveRegistry` | `call-agent` | User or handler factory | `BEDDEL-PRIM-002: registry not found in execution context metadata` |
| `tool_registry` | `dict[str, Callable]` | `tool` | User | `BEDDEL-PRIM-003: tool_registry not found in execution context metadata` |
| `tracer` | `ITracer` | OpenTelemetry adapter (optional) | User or adapter setup | Silent no-op (tracing is opt-in) |

**Wiring Rules:**
1. The `WorkflowExecutor` is responsible for injecting `llm_provider` and `lifecycle_hooks` — these are always available if the executor is properly constructed.
2. `workflow_loader`, `registry`, and `tool_registry` are caller-provided — the `create_beddel_handler` factory wires `registry` automatically, but `workflow_loader` and `tool_registry` require explicit user setup.
3. Optional keys (`lifecycle_hooks`, `tracer`) degrade gracefully — no error, just no-op behavior.
4. Required keys produce structured `BEDDEL-*` errors with the key name in the message, enabling immediate diagnosis.
5. Integration tests MUST verify the full wiring path: factory → executor → context → primitive → adapter (lesson §13.1).

---
