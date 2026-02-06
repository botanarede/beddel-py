# TASK.md — Ralph Loop Checklist

> **Agent:** main (Qwen Coder)
> **Loop:** Read → Implement → Test → Commit → Next
> **Max retries per task:** 3
> **Test command:** `pytest -x --timeout=30 && ruff check . && mypy src/`

---

## Phase 1: Unit Tests for Domain Core

- [ ] `tests/unit/domain/test_models.py` — Test all Pydantic models serialize/deserialize correctly, test exception hierarchy, test ErrorCode enum values
- [ ] `tests/unit/domain/test_parser.py` — Test YAMLParser.parse() with valid YAML (use fixtures/workflows/simple.yaml), test parse_file(), test invalid YAML raises ParseError, test validation errors, test validate() semantic checks (duplicate IDs, max_steps, fallback_step)
- [ ] `tests/unit/domain/test_resolver.py` — Test $input.* resolution, test $stepResult.* with nested paths, test $env.* resolution (mock os.environ), test inline substitution vs full-match (type preservation), test ResolutionError on missing keys
- [ ] `tests/unit/domain/test_executor.py` — Test sequential execution with mock primitives, test step condition skipping, test on_error skip strategy, test return template resolution, test workflow failure on step error, test lifecycle hooks called in order
- [ ] `tests/unit/domain/test_registry.py` — Test register decorator, test register_func, test get() returns correct function, test get() raises ExecutionError for unknown primitive, test list(), test has(), test duplicate registration raises ValueError

## Phase 2: Primitives

- [ ] `src/beddel/primitives/llm.py` — Implement llm primitive: resolve provider/model from config, build LLMRequest, call ILLMProvider.complete(), return LLMResponse. Register via @registry.register("llm")
- [ ] `src/beddel/primitives/chat.py` — Implement chat primitive: multi-turn with message history from config.messages, call ILLMProvider.complete(), return response. Register as "chat"
- [ ] `src/beddel/primitives/output.py` — Implement output-generator primitive: resolve config.template using VariableResolver, return resolved dict. Register as "output-generator"
- [ ] `src/beddel/primitives/call_agent.py` — Implement call-agent primitive: load nested workflow by agentId, execute via WorkflowExecutor recursively, return result. Register as "call-agent"
- [ ] `src/beddel/primitives/guardrail.py` — Implement guardrail primitive: validate config.input against config.schema using Pydantic, return ValidationResult. Register as "guardrail"
- [ ] `src/beddel/primitives/__init__.py` — Export all primitives, create default_registry() factory that registers all built-in primitives

## Phase 3: Unit Tests for Primitives

- [ ] `tests/unit/primitives/test_llm.py` — Test llm primitive with mocked ILLMProvider
- [ ] `tests/unit/primitives/test_chat.py` — Test chat primitive with message history
- [ ] `tests/unit/primitives/test_output.py` — Test output-generator template resolution
- [ ] `tests/unit/primitives/test_call_agent.py` — Test call-agent with nested workflow mock
- [ ] `tests/unit/primitives/test_guardrail.py` — Test guardrail validation pass/fail

## Phase 4: Adapters

- [ ] `src/beddel/adapters/litellm.py` — LiteLLMAdapter implementing ILLMProvider: wrap litellm.acompletion(), map response to LLMResponse, handle ProviderError
- [ ] `src/beddel/adapters/hooks.py` — LifecycleHooksAdapter implementing ILifecycleHook: event emitter pattern with register/emit, async dispatch
- [ ] `src/beddel/adapters/tracing.py` — OpenTelemetryAdapter implementing ITracer: create spans for workflow/step, record errors, use opentelemetry-api
- [ ] `src/beddel/adapters/__init__.py` — Export all adapters

## Phase 5: Integration

- [ ] `tests/integration/test_litellm.py` — Integration test with LiteLLMAdapter (use respx to mock HTTP, not real API calls)
- [ ] Wire up: create `beddel.create_engine()` factory in `__init__.py` that assembles WorkflowExecutor with default registry + LiteLLM adapter
- [ ] Verify full pipeline: parse YAML → resolve vars → execute with mock LLM → return result

## Phase 6: FastAPI Integration (Optional)

- [ ] `src/beddel/integrations/fastapi.py` — createBeddelHandler() that creates POST endpoint, SSE streaming support
- [ ] `tests/integration/test_fastapi.py` — Test FastAPI handler with TestClient

---

## Rules

1. One task at a time. Mark `[x]` when done.
2. After each task: `pytest -x --timeout=30 && ruff check . && mypy src/`
3. If all pass: `git add -A && git commit -m "feat(domain): <what you did>"`
4. If fail after 3 attempts: write to STUCK.md and move to next task.
5. Update PROGRESS.md after each commit.

## Reference Files

- `src/beddel/domain/models.py` — All Pydantic models and exception hierarchy
- `src/beddel/domain/ports.py` — Protocol interfaces (ILLMProvider, ITracer, ILifecycleHook)
- `src/beddel/domain/registry.py` — PrimitiveRegistry with @register decorator
- `src/beddel/domain/parser.py` — YAMLParser with yaml.safe_load + Pydantic validation
- `src/beddel/domain/resolver.py` — VariableResolver for $input.*, $stepResult.*, $env.*
- `src/beddel/domain/executor.py` — WorkflowExecutor async sequential
- `tests/fixtures/workflows/` — YAML fixtures (simple.yaml, multi_step.yaml, nested_agent.yaml)
- `docs/architecture/components.md` — Component specifications
- `docs/architecture/data-models.md` — Data model specifications
- `docs/architecture/error-handling-strategy.md` — Error codes and hierarchy

## DoD per Task (from BMAD story-dod-checklist)

- [ ] Implementation matches architecture docs
- [ ] No new ruff errors or warnings
- [ ] mypy strict passes
- [ ] Tests cover happy path + at least 1 error case
- [ ] Code has docstrings on public functions
