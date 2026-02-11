# 5. Epic 1: Adaptive Core Engine & Project Foundation

**Goal:** Establish the project's development infrastructure and deliver a testable, runnable workflow engine. A developer can `pip install`, define a YAML workflow with conditional branching and retry, execute it with an LLM primitive call, and verify results — all passing automated tests with spec fixtures as the source of truth.

## Story 1.1: Project Scaffolding, CI/CD & Documentation

As a developer,
I want the project repository to have proper build configuration, CI/CD pipeline, development tooling, and README documentation,
so that I can install the SDK, run tests, and contribute from day one.

**Acceptance Criteria:**
1. `pyproject.toml` is configured with hatchling build system, project metadata, Python 3.11+ requirement, all core dependencies (pydantic, litellm, pyyaml, opentelemetry-api, httpx), dev dependencies (pytest, pytest-asyncio, pytest-cov, ruff, mypy), and optional `[fastapi]` extra
2. GitHub Actions CI workflow runs on every PR: pytest with coverage, `ruff check .`, `ruff format --check .`, `mypy src/`
3. A release workflow (manual trigger or tag-based) builds the package and publishes to PyPI via hatchling
4. README.md includes: project description, installation instructions (`pip install beddel`), quickstart code example, development setup (install dev deps, run tests, lint, type check), and contribution guidelines placeholder
5. `.gitignore` includes `.env`, `__pycache__`, `dist/`, `*.egg-info/`, `.mypy_cache/`
6. The structured error code catalog is initialized with the `BEDDEL-` prefix convention and at least the domain codes: `PARSE`, `RESOLVE`, `EXEC`, `PRIM`, `ADAPT`

## Story 1.2: YAML Parser & Pydantic Models

As a developer,
I want to define workflows in YAML and have them validated into typed Python models,
so that I get immediate feedback on invalid workflow definitions.

**Acceptance Criteria:**
1. Pydantic 2.x models define the workflow schema: Workflow (metadata, steps, input schema), Step (id, primitive, config, if/then/else, execution strategy, timeout, parallel placeholder), ExecutionStrategy (type: fail/skip/retry/fallback, retry config with max_attempts/backoff/jitter)
2. Parser uses `yaml.safe_load()` exclusively and validates against Pydantic models
3. Variable references (`$input.*`, `$stepResult.*`, `$env.*`) are recognized in string fields
4. JSON Schema definitions in `spec/schemas/` match the Pydantic models
5. `spec/fixtures/invalid/` contains at least 3 invalid workflow files that the parser rejects with structured error codes (`BEDDEL-PARSE-*`)
6. `spec/fixtures/valid/` contains at least 2 valid workflow files including one with branching and execution strategies

## Story 1.3: Variable Resolver

As a developer,
I want variables in my YAML workflows to be resolved at runtime from inputs, step results, and environment,
so that I can build dynamic, data-driven workflows.

**Acceptance Criteria:**
1. Resolver supports `$input.*`, `$stepResult.<step_id>.*`, and `$env.*` namespaces out of the box
2. Custom namespaces can be registered via `resolver.register_namespace("name", handler_fn)` where `handler_fn` is a simple callable
3. Resolution is recursive for nested variable references
4. Unresolvable variables produce structured errors (`BEDDEL-RESOLVE-*`) with the variable path in the message
5. Spec fixtures in `expected/` define expected resolution outputs for test validation

## Story 1.4: Primitive Registry & LLM Primitive

As a developer,
I want to register and invoke primitives by name, starting with an LLM primitive,
so that my workflow steps can call LLM providers through a consistent interface.

**Acceptance Criteria:**
1. `@primitive("name")` decorator registers primitives in the registry with contract validation at registration time
2. Users can register custom primitives using the same decorator
3. `register_builtins()` populates the registry with all built-in primitives
4. The `llm` primitive supports single-turn invocation with configurable model, temperature, max_tokens
5. The `llm` primitive supports streaming via async generators
6. The `llm` primitive integrates with execution strategies (retry on transient failures)
7. The `llm` primitive reads `context.metadata["llm_provider"]` for the LLM provider instance

## Story 1.5: LiteLLM Adapter

As a developer,
I want to use any LLM provider (OpenAI, Gemini, Anthropic, Bedrock, etc.) without changing my workflow,
so that I'm not locked into a single provider.

**Acceptance Criteria:**
1. `LiteLLMAdapter` implements the `ILLMProvider` port interface
2. Supports all LiteLLM-supported providers via model string prefix (e.g., `gemini/gemini-2.0-flash`)
3. Explicitly resolves API keys from well-known environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) when no explicit `api_key` is provided — does not rely solely on LiteLLM auto-detection
4. Provider-specific configuration is handled via the adapter pattern
5. Integration test verifies the adapter reaches the `llm` primitive through the full execution path (executor → context → primitive → adapter)

## Story 1.6: Adaptive Workflow Executor

As a developer,
I want to execute multi-step workflows with conditional branching and configurable error strategies,
so that my workflows adapt to runtime conditions rather than just dispatching sequentially.

**Acceptance Criteria:**
1. Executor runs steps sequentially, evaluating `if` conditions to determine execution
2. Steps with `then`/`else` sub-steps execute the appropriate branch based on condition evaluation
3. Execution strategies are applied per step: `fail` (raise), `skip` (continue), `retry` (exponential backoff with jitter, configurable max_attempts), `fallback` (execute alternative step)
4. Step-level timeout support terminates long-running steps
5. `WorkflowExecutor.__init__` accepts optional `provider: ILLMProvider` and injects it into `ExecutionContext.metadata["llm_provider"]`
6. Lifecycle hooks are injected into `ExecutionContext.metadata["lifecycle_hooks"]`
7. The ExecutionContext Wiring Contract is documented: a table listing every metadata key, which primitive requires it, who provides it, and error behavior when absent
8. `execute_stream()` returns `AsyncGenerator[BeddelEvent, None]` for incremental event emission
9. End-to-end spec fixture test: a multi-step workflow with branching and retry executes successfully and matches expected results

## Story 1.7: Onboarding Example & Quickstart

As a new developer,
I want a complete getting-started example that I can run in under 15 minutes,
so that I can evaluate the SDK quickly and understand its value.

**Acceptance Criteria:**
1. A minimal "hello world" YAML workflow exists in `examples/workflows/` demonstrating: a single LLM call, `$input` variable resolution, and structured result output
2. A Python script in `examples/` executes the workflow programmatically and prints results
3. The quickstart is documented in README.md with copy-paste commands: install → set API key → create workflow → run → see output
4. Example uses stable model names only (no `-exp` suffixes) with comments noting model names may need updating
5. The complete flow is achievable in < 15 minutes from `pip install`

---
