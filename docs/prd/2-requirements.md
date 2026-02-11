# 2. Requirements

## 2.1 Functional Requirements

**Core Engine (Epic 1)**

- **FR1:** The SDK SHALL parse YAML workflow definitions using `yaml.safe_load()` with Pydantic 2.x validation, supporting workflow metadata, step definitions, variable references, conditional expressions, and execution strategy declarations
- **FR2:** The SDK SHALL resolve variables through an extensible namespace system supporting `$input.*`, `$stepResult.<step_id>.*`, `$env.*`, with a callable registration mechanism for custom namespaces (e.g., `resolver.register_namespace("memory", handler_fn)`). Resolution SHALL be recursive for nested references
- **FR3:** The SDK SHALL execute workflows adaptively with sequential execution, step-level conditional branching (`if/then/else` with optional `then` and `else` sub-steps), and configurable execution strategies per step (`fail`, `skip`, `retry` with exponential backoff and jitter, `fallback` to alternative step). Step-level timeout support SHALL be included
- **FR4:** The SDK SHALL provide a decorator-based primitive registry (`@primitive("name")`) that validates primitive contracts at registration time and is extensible by users for custom primitives
- **FR5:** The SDK SHALL include a built-in `llm` primitive for single-turn LLM invocation with configurable model, temperature, and max_tokens. Streaming SHALL be supported via async generators. The primitive SHALL integrate with execution strategies for retry on transient failures
- **FR6:** The SDK SHALL provide a LiteLLM adapter supporting 100+ LLM providers (OpenRouter, Google Gemini, AWS Bedrock, Anthropic, etc.) with provider-specific configuration via the adapter pattern. The adapter SHALL explicitly resolve API keys from well-known environment variables as a fallback, not relying solely on LiteLLM's auto-detection (per lesson §13.3)
- **FR7:** The SDK SHALL include YAML test fixtures in `spec/fixtures/` (valid/, invalid/, expected/) and JSON Schema definitions in `spec/schemas/` proving end-to-end workflow execution with branching and retry
- **FR8:** The `WorkflowExecutor` SHALL accept an optional `provider: ILLMProvider` parameter and inject it into `ExecutionContext.metadata["llm_provider"]` in both `execute()` and `execute_stream()`. Lifecycle hooks SHALL be injected into `metadata["lifecycle_hooks"]` at the same point (per lesson §13.1)
- **FR9:** Factory functions (e.g., `create_beddel_handler`) SHALL provide working defaults for all required dependencies — including auto-creating a `LiteLLMAdapter()` when no provider is supplied, and calling `register_builtins()` on default registries (per lessons §13.2, §13.11)

**Compositional Primitives (Epic 2)**

- **FR10:** The SDK SHALL provide a `chat` primitive for multi-turn conversational management with message history tracking, context windowing, and streaming support via async generators
- **FR11:** The SDK SHALL provide an `output-generator` primitive for template-based output rendering with variable interpolation via the VariableResolver. Documentation SHALL accurately describe the implementation as "variable interpolation via VariableResolver" (per lesson §13.9)
- **FR12:** The SDK SHALL provide a `call-agent` primitive for nested workflow invocation with configurable max depth, context passing, and result propagation
- **FR13:** The SDK SHALL provide a `guardrail` primitive for input/output validation with failure strategies: `raise` (hard fail), `return_errors` (soft fail), `correct` (auto-fix attempt), `delegate` (escalate to another primitive)
- **FR14:** The SDK SHALL provide a `tool` primitive for function invocation with schema discovery, input validation, and structured result handling, supporting both sync and async tools
- **FR15:** The SDK SHALL enforce structured output via Pydantic-based validation with JSON repair/recovery for malformed LLM responses and configurable repair strategies

**Observability & Integration (Epic 3)**

- **FR16:** The SDK SHALL generate OpenTelemetry spans for workflow execution, step execution, and primitive invocation, with token usage tracking per step/workflow and custom attributes for model, provider, and execution strategy
- **FR17:** The SDK SHALL provide a lifecycle hook system with events: `on_workflow_start`, `on_workflow_end`, `on_step_start`, `on_step_end`, `on_llm_start`, `on_llm_end`, `on_error`, `on_retry`. Hook dispatch SHALL use a single unified mechanism to avoid dual-channel mismatch (per lesson §13.10)
- **FR18:** The SDK SHALL provide a FastAPI handler factory (`create_beddel_handler`) for exposing workflows as HTTP endpoints, available as an optional extra (`pip install beddel[fastapi]`)
- **FR19:** The SDK SHALL provide an SSE streaming adapter for real-time streaming of workflow execution and LLM responses. The executor SHALL own event emission via `execute_stream()` returning `AsyncGenerator[BeddelEvent, None]` (per lesson §13.6). SSE serialization SHALL correctly handle multi-line data per the W3C SSE specification (per lesson §13.8)
- **FR20:** Cross-module utility functions SHALL use public naming (no underscore prefix) when imported across module boundaries (per lesson §13.7)

**Onboarding & Getting-Started Flow (PO Gap #2)**

- **FR21:** The SDK SHALL support a complete onboarding journey achievable in < 15 minutes:
  1. Install: `pip install beddel`
  2. Create: Write a YAML workflow file (with a documented minimal example)
  3. Execute: Run the workflow programmatically (`from beddel import ...`)
  4. See results: Observe structured output with step results and execution metadata
- **FR22:** The SDK SHALL include a documented minimal "hello world" workflow example that demonstrates: a single LLM call step, variable resolution from `$input`, and structured result output — executable with zero configuration beyond an LLM API key in an environment variable
- **FR23:** Example workflows SHALL use stable model names only (never experimental `-exp` suffixes) and include comments noting that model names may need updating (per lesson §13.4)

**CI/CD Pipeline (PO Gap #1)**

- **FR24:** The project SHALL include a CI/CD pipeline configuration (GitHub Actions) that runs on every pull request:
  1. Automated test suite (`pytest`) with coverage reporting
  2. Lint check (`ruff check .`)
  3. Type check (`mypy src/`)
  4. Format check (`ruff format --check .`)
- **FR25:** The project SHALL define a PyPI publishing strategy: automated package build via `hatchling`, version management in `pyproject.toml`, and a release workflow (manual trigger or tag-based) that publishes to PyPI

**Documentation (PO Should-Fix)**

- **FR26:** Epic 1 SHALL include README setup with: project description, installation instructions, quickstart example, development setup (install dev dependencies, run tests, lint, type check), and contribution guidelines placeholder

## 2.2 Non-Functional Requirements

**Performance**

- **NFR1:** Execution overhead SHALL be < 5ms per step (excluding LLM latency and network I/O)
- **NFR2:** YAML parsing and Pydantic validation SHALL complete in < 100ms for workflows up to 50 steps

**Quality & Testing**

- **NFR3:** Domain logic test coverage SHALL exceed 80%, measured by `pytest-cov`
- **NFR4:** All spec fixtures SHALL be the single source of truth for cross-SDK behavioral validation. Every primitive and every execution strategy SHALL have corresponding fixtures
- **NFR5:** Port/adapter architecture SHALL be validated by integration tests that verify adapters reach primitives through the full execution path — not just unit tests at each layer boundary (per lesson §13.1)
- **NFR6:** Streaming and serialization code SHALL be tested with realistic payloads including multi-line content, unicode, and edge cases (per lesson §13.8)

**Security**

- **NFR7:** YAML parsing SHALL use `yaml.safe_load()` exclusively — no `yaml.load()`, no `eval()`, no dynamic code execution
- **NFR8:** Secrets and API keys SHALL be provided via environment variables only — never hardcoded in source or YAML files
- **NFR9:** The adapter layer SHALL explicitly resolve API keys from well-known environment variables, not relying on third-party library auto-detection for critical auth paths (per lesson §13.3)

**Architecture**

- **NFR10:** The domain core (parser, resolver, executor, registry, models, ports) SHALL NOT import from adapters or integrations. All external dependencies SHALL flow through port interfaces (Hexagonal Architecture)
- **NFR11:** All limits and thresholds SHALL be configurable with sensible defaults — no hardcoded limits without override capability
- **NFR12:** The SDK SHALL be async-first using `asyncio` with `async/await` throughout

**Documentation & API**

- **NFR13:** 100% of public API functions and classes SHALL have docstrings
- **NFR14:** All example workflows SHALL use stable, non-experimental model names

**Error Handling**

- **NFR15:** The SDK SHALL implement a structured error code catalog with the prefix `BEDDEL-` followed by a domain code and sequence number (e.g., `BEDDEL-EXEC-001`, `BEDDEL-PARSE-001`). Each error code SHALL have a documented meaning, likely cause, and suggested resolution
- **NFR16:** Error handling SHALL use graduated strategies: fail, skip, retry (with exponential backoff and jitter), fallback, and delegate — not binary fail/skip only
- **NFR17:** Factory functions SHALL initialize default instances to a usable state. An empty registry or missing provider SHALL never be the default (per lessons §13.2, §13.11)

**Wiring Contract (PO Should-Fix)**

- **NFR18:** The project SHALL define and document an ExecutionContext Wiring Contract — a table listing every `metadata` key, which primitive requires it, who is responsible for providing it (executor, handler factory, or user), and the error behavior when absent. This contract SHALL be enforced by integration tests (per lesson §13.5)

---
