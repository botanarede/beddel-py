# Project Brief: Beddel

> **Date:** February 2026
> **Status:** Draft

---

## 1. Executive Summary

Beddel is an Agent-Native Workflow Engine — a Python SDK that enables declarative YAML-based AI workflows with compositional primitives and adaptive execution. Developers define outcome-driven workflows in YAML; the engine composes atomic primitives into goal-oriented execution flows with conditional branching, reflection loops, human checkpoints, and multi-provider LLM abstraction.

The core insight: 95% of production AI workloads follow predictable workflow patterns, while 5% require adaptive agent loops. Beddel handles both through a single declarative surface — YAML for the backbone, code escape hatches for complex logic. The engine adapts execution based on conditions, errors, and agent judgment — not just sequential dispatch.

Target audience: Python developers building AI agents who want production-ready workflows without boilerplate code.

---

## 2. Problem Statement

### Current State & Pain Points

1. **Code-Heavy Agent Construction:** Building AI workflows requires hundreds of lines of imperative Python — prompt chains, retry logic, error handling, provider switching — all hand-wired for every project
2. **Missing Agent-Native Patterns:** No existing tool provides declarative support for reflection loops, human-in-the-loop approval, episodic memory, or goal-oriented execution as first-class concepts
3. **Fragmented Tooling:** Developers stitch together 5-10 libraries (LLM SDKs, prompt managers, observability, guardrails) with no unified execution model
4. **Provider Lock-in:** Switching LLM providers means rewriting integration code; no abstraction layer handles routing, tier selection, or fallback natively
5. **No Declarative Agent Behavior:** Goal-oriented patterns (reflect-evaluate-refine, branch-on-condition, pause-for-human) cannot be expressed in configuration — they must be coded from scratch every time

### Why Existing Solutions Fall Short

| Solution | Gap |
|----------|-----|
| LangChain / LangGraph | Complex graph abstractions; no declarative YAML surface; agent patterns require imperative code |
| AutoGen | Multi-agent conversation focus, not workflow orchestration; no YAML definitions |
| CrewAI | Role-based agent teams; lacks fine-grained primitive composition and adaptive execution |
| Native SDKs (OpenAI, Anthropic) | Zero workflow orchestration; every production feature is DIY |
| Prefect / Airflow | Data pipeline tools; no LLM-native primitives, no agent patterns |
| Docker cagent | YAML-first but limited control flow; no reflection, HITL, or goal-oriented patterns |

### Why Now

- PayPal's research (arXiv 2512.19769, Nov 2025) demonstrated declarative DSL reduces development time by 60% and deploys 3x faster than imperative code, with millions of daily interactions in production
- Memory is the next frontier — Mem0 raised $24M Series A with 41K GitHub stars and 186M API calls/quarter, proving demand for episodic memory in agent systems
- Model routing saves real money — RouteLLM (UC Berkeley) demonstrates open-source tier-based routing via preference data; three-tier traffic splits cut LLM costs significantly
- Microsoft (Nov 2025) recommends hybrid approach: workflow-first for governance, code-first for complex logic — exactly Beddel's design philosophy
- Google ADK (Jun 2026) documents both pipeline and goal-oriented patterns, recommending pipelines for well-defined processes and agent loops for dynamic tasks
- Gartner estimates <5% of enterprise apps have real AI agents by end 2025 — the 95/5 pipeline-to-agent ratio in production validates Beddel's dual-mode approach
- Enterprise adoption requires HITL + PII protection + observability as table stakes

---

## 3. Proposed Solution

A **Hexagonal Architecture** Python SDK that:

1. **Parses** declarative YAML workflows with Pydantic validation
2. **Resolves** variables through an extensible namespace system (`$input`, `$stepResult`, `$env`, plus pluggable namespaces)
3. **Executes** workflows adaptively — sequential by default, with conditional branching (`if/then/else`), configurable execution strategies (retry, fallback, skip, delegate), and step-level timeout support
4. **Composes** atomic primitives into outcome-driven behaviors through a decorator-based registry

### Core Concept

Primitives are atomic building blocks. Workflows are declarative compositions. The engine adapts execution based on conditions, errors, and agent judgment — not just sequential dispatch. Control flow supports branching, loops, and parallel fan-out natively.

### Key Differentiators

- **YAML-First:** Workflows are configuration, not code. Complex logic uses code escape hatches, not the other way around
- **Adaptive Execution:** The executor handles branching, retry with backoff, reflection loops, and parallel steps natively — not bolted on after the fact
- **Agent-Native by Design:** Reflection, HITL, memory, and goal-oriented patterns are first-class compositional primitives, not afterthoughts
- **Multi-Provider Abstraction:** LiteLLM provides 100+ provider support with tier selection (fast/balanced/powerful)
- **Spec-Driven Testing:** Shared YAML fixtures in `spec/` enable cross-SDK validation and declarative test scenarios
- **Execution Strategies:** Error handling goes beyond fail/skip — retry with exponential backoff, fallback to alternative primitives, delegate to agent judgment, circuit breaker for provider outages

---

## 4. Target Users

### Primary: Python AI Developers

- **Profile:** Backend developers (2-5 years experience), comfortable with async Python and YAML
- **Current Workflow:** Building agents with OpenAI SDK, LangChain, or raw HTTP calls; managing prompt chains and retry logic manually
- **Pain Points:** Boilerplate code for every workflow, no standard patterns for agent behavior, difficulty adding observability and guardrails
- **Goals:** Ship production-ready AI features faster with less code and more confidence

### Secondary: AI/ML Platform Teams

- **Profile:** ML engineers and platform teams integrating LLMs into existing Python systems
- **Pain Points:** No standardized way to express agent workflows; prototype-to-production gap; monitoring LLM calls across providers
- **Goals:** Standardized, observable, auditable AI workflow patterns that the whole team can use

---

## 5. Goals & Success Metrics

### Business Objectives

- Deliver a testable, runnable SDK with Epic 1 (Adaptive Core Engine) — end-to-end from YAML parse to workflow result
- Achieve 80%+ test coverage on domain logic
- Demonstrate a multi-step workflow with branching, retry, and LLM invocation working end-to-end

### User Success Metrics

- Time to first workflow: < 15 minutes from `pip install`
- Lines of code reduction vs raw SDK: 70%+
- Workflow success rate in production: > 95%

### Key Performance Indicators

| KPI | Target |
|-----|--------|
| Domain Test Coverage | > 80% |
| Execution Overhead | < 5ms per step (excluding LLM latency) |
| Public API Docstrings | 100% |
| Spec Fixture Coverage | Every primitive + every execution strategy |

---

## 6. MVP Scope

### Epic 1: Adaptive Core Engine

The foundational epic. Delivers a testable, runnable workflow engine end-to-end. A developer can define a YAML workflow, execute it, and get results — with branching, retry, and LLM invocation all working.

- **YAML Parser** — Secure loading (`yaml.safe_load()`) with Pydantic 2.x validation. Supports workflow metadata, step definitions, variable references, conditional expressions, and execution strategy declarations
- **Variable Resolver** — Extensible namespace system supporting `$input.*`, `$stepResult.<step_id>.*`, `$env.*` with a simple callable registration mechanism for future namespaces (`$memory`, `$context`). Example: `resolver.register_namespace("memory", handler_fn)`. Recursive resolution for nested references. No hardcoded namespace limits — the resolver iterates registered handlers
- **Adaptive Workflow Executor** — Sequential execution with step-level conditional branching (`if/then/else` — each step can declare optional `then` and `else` sub-steps), configurable execution strategies per step (`fail`, `skip`, `retry` with exponential backoff and jitter, `fallback` to alternative step). Step-level timeout support. The data model reserves a `parallel` field for future use (Epic 4). The executor evaluates conditions and adapts flow — not a pure sequential dispatcher
- **Primitive Registry** — Decorator-based registration (`@primitive("llm")`). Extensible by users for custom primitives. Registry validates primitive contracts at registration time
- **LLM Primitive** — Single-turn LLM invocation with configurable model, temperature, max_tokens. Supports streaming via async generators. Structured error reporting with execution strategy integration (retry on transient failures)
- **LiteLLM Adapter** — Multi-provider abstraction wrapping LiteLLM. Supports OpenRouter, Google Gemini, AWS Bedrock, Anthropic, and all LiteLLM-supported providers. Provider-specific configuration via adapter pattern
- **Spec Fixtures** — YAML test fixtures in `spec/fixtures/` (valid/, invalid/, expected/) proving a multi-step workflow with branching and retry works end-to-end. JSON Schema definitions in `spec/schemas/`

**Epic 1 Success Criteria:** A developer can define a multi-step YAML workflow with conditional branching and retry, execute it programmatically with an LLM primitive call, and verify results — all passing automated tests with spec/ fixtures as the source of truth.

### Epic 2: Compositional Primitives

Expands the primitive library with the full set of compositional building blocks.

- **chat Primitive** — Multi-turn conversational management with message history tracking, context windowing, and streaming support via async generators
- **output-generator Primitive** — Template-based output rendering with variable interpolation. Supports structured output formatting (JSON, Markdown, custom templates)
- **call-agent Primitive** — Nested workflow invocation with configurable max depth, context passing, and result propagation. Enables workflow composition and agent coordination
- **guardrail Primitive** — Input/output validation with flexible failure strategies: `raise` (hard fail), `return_errors` (soft fail), `correct` (auto-fix attempt), `delegate` (escalate to another primitive)
- **tool Primitive** — Function invocation with schema discovery, input validation, and structured result handling. Supports both sync and async tools
- **Structured Output Enforcement** — Pydantic-based output validation with JSON repair/recovery for malformed LLM responses. Configurable repair strategies before raising errors

### Epic 3: Observability & Integration

Production-grade observability and framework integration.

- **OpenTelemetry Tracing** — Span generation for workflow execution, step execution, and primitive invocation. Token usage tracking per step and per workflow. Custom attributes for model, provider, and execution strategy
- **Lifecycle Hooks** — Granular event system: `on_workflow_start`, `on_workflow_end`, `on_step_start`, `on_step_end`, `on_llm_start`, `on_llm_end`, `on_error`, `on_retry`. User-registerable hook handlers
- **FastAPI Integration** — Handler factory for exposing workflows as HTTP endpoints. Optional extra (`pip install beddel[fastapi]`). Request/response mapping with Pydantic models
- **SSE Streaming Adapter** — Server-Sent Events adapter for real-time streaming of workflow execution and LLM responses through FastAPI endpoints

**MVP Success Criteria:** Epics 1-3 deliver a complete, observable, framework-integrated workflow engine. A developer can install the SDK, define YAML workflows with branching and retry, execute them with multiple LLM providers, observe traces, and expose workflows as HTTP endpoints.

### Out of Scope for MVP

- Web UI / dashboard
- Database adapters (beyond pluggable interfaces)
- Multi-tenancy / API key management
- Auto-scaling / distributed execution
- Non-Python SDKs
- Goal-oriented execution loops (Epic 4)
- Human-in-the-loop (Epic 5)
- PII tokenization (Epic 5)

---

## 7. Post-MVP Vision

### Epic 4: Adaptive Execution Patterns

Advanced control flow patterns that elevate workflows from structured pipelines to adaptive agent behaviors.

- **Reflection Loops** — Generate-evaluate-refine cycle with configurable max iterations, structured feedback, and convergence detection. A `reflect` step evaluates output against criteria and decides whether to refine or accept
- **Goal-Oriented Execution** — Loop-until-outcome pattern where the executor repeats a step sequence until a declared goal condition is met, with configurable max attempts and backoff
- **Parallel Execution** — `asyncio.gather` for independent steps declared with `parallel: true`. Fan-out/fan-in with result aggregation and configurable error semantics (fail-fast vs collect-all)
- **Circuit Breaker** — Provider-level circuit breaker with configurable failure thresholds, recovery windows, and fallback routing. Integrates with execution strategies for intelligent retry

### Epic 5: Agent Autonomy & Safety

Enterprise-grade safety and stateful execution patterns.

- **Human-in-the-Loop** — Pause/resume execution at designated checkpoints. Approval mechanism with timeout, escalation, and risk-based policies (auto-approve low-risk, require approval for high-risk). Inspired by Athenic's DB-backed state snapshots for resume
- **Model Tier Selection** — Declarative model routing: `fast` (cheap/quick), `balanced` (default), `powerful` (best quality). Maps to concrete models per provider. Inspired by RouteLLM's preference-based routing
- **PII Tokenization** — Intercept sensitive data before LLM calls, replace with tokens, de-tokenize after response. Configurable patterns (regex-based initially, NER adapter later)
- **State Persistence / Checkpoints** — Serialize execution context at configurable points. Resume interrupted workflows from last checkpoint. Pluggable storage backend (JSON initially, msgpack/DB later)

### Future: Ecosystem & Enterprise

- **Episodic Memory** — Vector store integration for cross-workflow context. Store and retrieve relevant context from past executions. Initial adapter for Mem0, with interface for other vector stores
- **Skill Composition** — Workflows as reusable skills. Import and compose workflows within other workflows. Skill registry with versioning
- **Multi-Agent Coordination** — Enhanced `call-agent` with handoff patterns, shared context, and agent-to-agent communication protocols. Swarm patterns for complex multi-agent scenarios
- **Workflow Marketplace** — Community-contributed workflow templates and skills
- **Multi-Language SDKs** — Python as canonical source; AI-assisted translation to TypeScript, Go, Rust. Shared `spec/` fixtures ensure behavioral parity across implementations
- **IDE Extension** — VS Code / Kiro extension for YAML authoring with autocomplete, validation, and visual workflow preview

---

## 8. Technical Considerations

### Platform Requirements

| Requirement | Specification |
|-------------|---------------|
| Python | 3.11+ required (modern async, typing, performance) |
| Async Runtime | `asyncio` with `async/await` throughout |
| Framework | Framework-agnostic core; FastAPI via `[fastapi]` optional extra |
| Security | `yaml.safe_load()` exclusively; secrets via environment variables |

### Core Dependencies

| Package | Purpose |
|---------|---------|
| `pydantic` 2.x | Schema validation, structured outputs, model definitions |
| `litellm` | Multi-provider LLM abstraction (100+ providers) |
| `pyyaml` 6.x | YAML parsing (`safe_load` only) |
| `opentelemetry-api` 1.x | Observability and tracing |
| `httpx` 0.27+ | Async HTTP client |

### Build & Quality Tools

| Tool | Purpose |
|------|---------|
| `hatchling` | Build system (PEP 517) |
| `pytest` + `pytest-asyncio` | Testing framework with async support |
| `ruff` | Linting and formatting (single tool) |
| `mypy` | Static type checking with strict mode |

### Architecture

- **Pattern:** Hexagonal Architecture (Ports & Adapters)
- **Domain Core:** Parser, Resolver, Executor (adaptive), Registry, Models, Ports (abstract interfaces)
- **Compositional Primitives:** `llm`, `chat`, `output-generator`, `call-agent`, `guardrail`, `tool`
- **Adapters:** LiteLLM (providers), OpenTelemetry (tracing), Lifecycle Hooks (events), Memory (Mem0), PII Tokenizer
- **Integrations:** FastAPI handler, SSE streaming
- **Key Principle:** Domain core MUST NOT import from adapters or integrations. All external dependencies flow through port interfaces.

### Repository Structure

```
beddel/
├── spec/                      # Shared specification — single source of truth
│   ├── schemas/               # JSON Schema definitions for workflow format
│   ├── fixtures/              # YAML test fixtures
│   │   ├── valid/             # Valid workflow definitions
│   │   ├── invalid/           # Invalid workflows (parser rejection tests)
│   │   └── expected/          # Expected execution results
│   └── tests/                 # Cross-SDK test files (pytest)
├── src/
│   └── beddel-py/             # Python SDK
│       ├── src/beddel/
│       │   ├── domain/        # Core: parser, resolver, executor, registry, models, ports
│       │   ├── primitives/    # Compositional primitives (llm, chat, output, etc.)
│       │   ├── adapters/      # External integrations (LiteLLM, OTel, Memory, PII)
│       │   └── integrations/  # Framework extras (FastAPI, SSE)
│       └── tests/             # SDK-specific unit tests
├── docs/                      # Documentation
│   ├── brief.md               # This file
│   ├── prd/                   # Product requirements
│   ├── architecture/          # Technical architecture
│   └── stories/               # BMAD stories (task tracking)
└── .bmad-core/                # BMAD Method
```

---

## 9. Constraints & Assumptions

### Constraints

| Area | Detail |
|------|--------|
| Team | Solo developer / small team; 3-agent hybrid strategy (Kiro + architect + Digger) |
| Budget | Budget-conscious — architect agent used surgically (2-4 sessions), Digger (free tier) used liberally |
| Language | Python 3.11+ only — leverages modern async, typing, and performance features |
| Security | `yaml.safe_load()` exclusively; secrets via environment variables only; no `eval()` or dynamic code execution |
| Testing | `spec/` at repo root is the single source of truth for fixtures shared across future SDKs |
| Scope | No web UI, no database, no multi-tenancy in MVP |

### Key Assumptions

- Python 3.11+ adoption is sufficient for the target audience (data science and AI communities are on 3.11+ widely)
- LiteLLM maintains backward compatibility across updates (adapter pattern absorbs breaking changes if not)
- Developers prefer YAML over Python for expressing workflow structure (PayPal research supports this)
- The hybrid approach (YAML backbone + code escape hatches) covers 95%+ of use cases
- FastAPI + SSE covers streaming requirements for the foreseeable future
- Pydantic 2.x is stable and performant enough for runtime validation on every step
- Async-first design does not create adoption barriers (target audience is comfortable with `async/await`)

---

## 10. Risks & Open Questions

### Key Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Executor complexity | High | Start with sequential + branching + retry in Epic 1; add reflection/parallel in Epic 4. Incremental complexity |
| LiteLLM API changes | Medium | Version pinning + adapter pattern absorbs breaking changes at the port boundary |
| Reflection loop instability | Medium | Max iteration limits, structured feedback schemas, convergence detection. Deferred to Epic 4 |
| HITL integration complexity | Medium | Start with simple pause/resume; external service integration deferred to post-MVP |
| PII detection accuracy | Medium | Regex-based initially (known patterns); NER adapter as future enhancement |
| Context overflow in long workflows | Medium | Step-level result scoping; checkpoint-based context windowing in Epic 5 |
| Spec fixture maintenance burden | Low | Fixtures are small YAML files; automated validation ensures they stay in sync |

### Open Questions

1. ~~Should the plugin system for variable namespaces use entry points, decorators, or both?~~ **Decided:** Simple callable registration (`resolver.register_namespace("memory", handler_fn)`) — entry points are overkill for an SDK, decorator registry adds coupling
2. What convergence criteria should reflection loops use by default (LLM-as-judge, score threshold, diff-based)?
3. How should HITL approval integrate with external services (Slack, email, webhook)?
4. Should tier selection be per-step, per-workflow, or both?
5. What serialization format for state persistence checkpoints (JSON, pickle, msgpack)?
6. What error semantics for parallel execution — fail-fast or collect-all-errors?

### Areas Needing Further Research

- Optimal circuit breaker thresholds for LLM providers (failure rates vary significantly by provider)
- Memory summarization strategies for long-running workflows
- PII detection patterns across languages (regex coverage vs NER accuracy tradeoffs)
- Structured output repair strategies (JSON healing heuristics vs LLM-based repair)

---

## 11. Appendices

### A. Research Summary

Three independent studies informed this brief:

1. **PayPal YAML DSL Study (arXiv 2512.19769, Nov 2025):** Demonstrated 60% reduction in development time and 3x faster deployment using declarative YAML for AI workflows vs imperative code. Millions of daily interactions in production validate the approach at scale.

2. **Agent-Native Patterns Analysis:** Cross-referenced LangGraph, AutoGen, CrewAI, Google ADK, and Semantic Kernel to identify consensus patterns. If/then/else branching (3-study consensus), human-in-the-loop (3-study consensus), reflection loops (2-study consensus), and goal-oriented execution (2-study consensus) emerged as critical capabilities. Parallel execution, circuit breaker, episodic memory, and PII tokenization had 2-study consensus at high priority.

3. **Memory & Enterprise Readiness Survey:** Mem0's traction ($24M Series A, 41K GitHub stars, 186M API calls/quarter) validates episodic memory demand. Athenic's approval workflows with DB-backed state snapshots demonstrate HITL patterns. Enterprise adoption requires HITL + PII + observability as baseline capabilities.

### B. Anti-Pattern Analysis

A comprehensive codebase analysis identified patterns that this design explicitly addresses:

| Anti-Pattern | Resolution |
|-------------|------------|
| Sequential-only execution (pure dispatcher) | Adaptive executor with branching, loops, and parallel support |
| Single-pass LLM calls (no self-correction) | Execution strategies with retry, backoff, reflection loops |
| Hardcoded variable namespaces (3 only) | Plugin-based namespace system, extensible by registration |
| Binary error handling (fail/skip only) | Graduated strategies: fail, skip, retry, fallback, delegate |
| No control flow beyond skip gates | If/then/else branching, goal-oriented loops, parallel fan-out |
| Agent as router (no autonomy) | Agent judgment delegation in execution strategies |
| Hardcoded limits without override | All limits configurable with sensible defaults |

### C. Recommendation Consensus (18 Recommendations from 3 Studies)

| Priority | Recommendations |
|----------|----------------|
| MAX (3-study) | If/Then/Else Branching, Human-in-the-Loop |
| High (2-study) | Goal-Oriented Execution, Reflection Loops, PII Tokenization, Episodic Memory, Circuit Breaker / Retry |
| High (1-study) | State Persistence / Checkpoints, Tier Selection |
| Evaluate | Parallel Execution, Declarative Testing, Skill Composition, Parity Validation, Multi-Agent Coordination |
| Already OK | Observability / Tracing, Atomic Primitives |
| N/A | Language-Agnostic Runtime (Python by design) |
| Aspirational | Workflow Marketplace |

---

## 12. Next Steps

1. **PM:** Generate PRD from this brief → `@pm *create-doc prd`
2. **Architect:** Design technical architecture → `@architect *create-doc architecture`
3. **SM:** Draft Epic 1 stories → `@sm *create-next-story`
4. **Dev:** Begin implementation after story approval

---

## 13. Post-Implementation Lessons Learned

> **Date:** February 11, 2026
> **Context:** After completing Epics 1-5 and Story 6.1, the following issues were discovered during manual end-to-end testing and an independent architecture audit (GPT-5.2). Each section documents a real problem, its root cause, and the resolution or recommendation — so future epics and SDK versions avoid repeating them.
>
> **Sources:**
> - Manual testing session (Kiro + developer, 2026-02-11)
> - Architecture audit report (`report-beddel-gpt.md`, GPT-5.2 via Digger, 2026-02-11)
> - Story 6.1 implementation and QA review

---

### 13.1 LLM Provider Not Injected into Execution Context

**Problem:** `WorkflowExecutor.execute()` created `ExecutionContext` with an empty `metadata` dict. The `llm` and `chat` primitives expect `context.metadata["llm_provider"]` to contain an `ILLMProvider` instance. Every real workflow using LLM calls failed with `BEDDEL-EXEC-001: llm_provider not found in execution context metadata`.

**Root Cause:** The hexagonal architecture correctly defined the `ILLMProvider` port and the `LiteLLMAdapter` adapter, but the wiring layer (executor + FastAPI integration) never connected them. `create_beddel_handler` accepted a `provider` parameter but discarded it — the executor had no mechanism to receive or inject it.

**Resolution:** `WorkflowExecutor.__init__` now accepts an optional `provider: ILLMProvider` parameter and injects it into `ExecutionContext.metadata["llm_provider"]` in both `execute()` and `execute_stream()`. Lifecycle hooks are also injected into `metadata["lifecycle_hooks"]` at the same point.

**Lesson:** Port/adapter architecture requires explicit wiring tests. Every port interface should have an integration test that verifies the adapter reaches the primitive through the full execution path — not just unit tests at each layer boundary.

---

### 13.2 No Default LLM Provider in FastAPI Handler

**Problem:** `create_beddel_handler()` required the caller to explicitly pass a `provider` argument. The example app (`examples/fastapi_app.py`) didn't pass one, so every workflow failed silently at runtime.

**Root Cause:** The handler factory assumed the caller would always provide dependencies. No sensible default was configured.

**Resolution:** When `provider is None`, `create_beddel_handler` now auto-creates a `LiteLLMAdapter()` as the default provider. This follows the convention of "sensible defaults, explicit overrides."

**Lesson:** Integration factories (handler creators, engine builders) must provide working defaults for all required dependencies. If a dependency is truly optional, the primitive should handle its absence gracefully. If it's required, the factory must supply a default.

---

### 13.3 LiteLLM Does Not Auto-Resolve API Keys from Environment

**Problem:** LiteLLM 1.81.8 did not automatically resolve `GEMINI_API_KEY` from environment variables when calling `litellm.acompletion()` with `model="gemini/gemini-2.0-flash"`. The env var was set and visible to Python (`os.environ`), but LiteLLM sent an invalid/empty key to the Google API.

**Root Cause:** Likely a regression or behavior change in LiteLLM >= 1.80. Passing `api_key` explicitly in the `acompletion()` call worked; relying on env var auto-detection did not.

**Resolution:** `LiteLLMAdapter._build_params()` now explicitly resolves the API key from well-known environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) based on the model prefix when no explicit `api_key` is provided. This makes the adapter resilient to LiteLLM env var handling changes.

**Lesson:** Never rely on third-party library env var auto-detection for critical auth paths. Always implement explicit fallback resolution in the adapter layer. Pin and test against specific library versions.

---

### 13.4 Example Workflow Used Discontinued Model Name

**Problem:** `examples/workflows/simple.yaml` referenced `gemini-2.0-flash-exp`, a Google experimental model that was no longer available. The workflow failed with `API key not valid` (misleading error from Google's API).

**Root Cause:** Experimental model names (`-exp` suffix) are temporary and get retired without notice. The YAML was written during development and never updated.

**Resolution:** Updated to `gemini/gemini-2.0-flash` (stable model with `gemini/` prefix for AI Studio routing). Both `simple.yaml` and `streaming.yaml` now use the same stable provider.

**Lesson:** Example workflows must use stable model names, never experimental ones. Add a comment in YAML files noting that model names may need updating. Consider a CI check that validates example workflows against available models.

---

### 13.5 ExecutionContext Metadata Wiring Contract Undefined

**Problem:** Multiple primitives (`llm`, `chat`, `call-agent`, `tool`) depend on specific keys in `ExecutionContext.metadata` (`llm_provider`, `lifecycle_hooks`, `workflow_loader`, `registry`, `tool_registry`), but there was no documented contract specifying which keys are required, who provides them, and what happens when they're missing.

**Root Cause:** The metadata dict was designed as a flexible extension point, but without a contract it became a source of runtime surprises. Each primitive silently assumed its dependencies would be present.

**Resolution (partial):** `llm_provider` and `lifecycle_hooks` are now injected by the executor. The remaining keys (`workflow_loader`, `registry` for `call-agent`; `tool_registry` for `tool`) still require explicit wiring by the caller.

**Recommendation:** Define and document an `ExecutionContext Wiring Contract` — a table listing every metadata key, which primitive requires it, who is responsible for providing it (executor, handler factory, or user), and the error behavior when absent. This should be in the architecture docs and enforced by integration tests.

---

### 13.6 Streaming Model: Global Detection, Not Incremental Execution

**Problem:** The FastAPI integration determined streaming mode by checking if any step in the workflow had `stream: true` (`_is_streaming_workflow()`). When streaming was detected, the original implementation called `await executor.execute()` and then tried to iterate the result — a "wait for everything, then stream" anti-pattern that defeated the purpose of streaming.

**Root Cause:** The initial design (Stories 5.1/5.2) treated streaming as an output format concern rather than an execution concern. There was no `execute_stream()` method on the executor.

**Resolution (Story 6.1):** Added `WorkflowExecutor.execute_stream()` returning `AsyncGenerator[BeddelEvent, None]`. The FastAPI `_sse_bridge()` now calls `execute_stream()` directly and pipes events through `BeddelSSEAdapter.stream_events()`. Events are yielded incrementally at each lifecycle point (step start, text chunks, step end, etc.).

**Lesson:** Streaming must be designed as an execution-level concern from the start, not bolted on as a response format adapter. The executor should own the event emission lifecycle.

---

### 13.7 SSE Adapter: Private Function Imported Cross-Module

**Problem:** `_build_error_event` in `integrations/sse.py` was a private function (underscore prefix) but was imported by `integrations/fastapi.py`. This violated Python naming conventions and made the dependency invisible to refactoring tools.

**Resolution (Story 6.1, Task 3):** Promoted to public `build_error_event` and added to `__all__`.

**Lesson:** If a function is used across module boundaries, it must be public. Enforce this with a linting rule or code review checklist.

---

### 13.8 SSE Serialize Did Not Handle Multi-Line Data

**Problem:** `SSEEvent.serialize()` emitted multi-line data as a single `data:` field, which violates the W3C SSE specification. Clients would receive corrupted events when LLM responses contained newlines.

**Resolution (Story 6.1, Task 3):** `serialize()` now splits `self.data` on `\n` and emits each line as a separate `data:` field per the SSE spec.

**Lesson:** Protocol compliance must be tested with realistic payloads. Add test cases with multi-line content, unicode, and edge cases (empty lines, trailing newlines) for any serialization code.

---

### 13.9 output-generator: Documentation Says Jinja2, Implementation Uses Variable Resolver

**Problem:** Architecture docs and PRD reference "Jinja2-style templating" for the `output-generator` primitive, but the actual implementation simply returns `config["template"]` after variable resolution — no Jinja2, no template engine.

**Root Cause:** The design evolved during implementation. Variable resolution via `VariableResolver` was sufficient for MVP, but docs were never updated.

**Recommendation:** Either align docs to say "variable interpolation via VariableResolver" (simpler, current behavior), or add Jinja2 support in a future story. The current behavior is not wrong — it's just undocumented.

---

### 13.10 Lifecycle Hooks: Dual Channel Mismatch

**Problem:** The executor fires workflow/step-level hooks (`on_workflow_start`, `on_step_start`, etc.) from its own loop. But `on_llm_start`/`on_llm_end` hooks are fired inside the `llm` primitive by reading `context.metadata["lifecycle_hooks"]`. This creates two separate hook channels — the executor's hook list and the metadata hook list — which could diverge if not wired identically.

**Resolution (partial):** The executor now injects `self._hooks` into `context.metadata["lifecycle_hooks"]`, ensuring both channels reference the same hook instances.

**Recommendation:** Consider unifying hook dispatch into a single mechanism. Either the executor should fire all hooks (including LLM-level), or all hooks should be resolved from context metadata. Two channels is a maintenance risk.

---

### 13.11 Primitive Registry Was Empty by Default

**Problem:** `create_beddel_handler` originally created an empty `PrimitiveRegistry()` when `registry is None`, without calling `register_builtins()`. Every workflow failed with `BEDDEL-EXEC-002: Primitive 'llm' not found in registry`.

**Resolution:** The handler factory now calls `register_builtins(effective_registry)` after creating the default registry. This was fixed before the manual testing session but is documented here as it was a known issue in the steering file.

**Lesson:** Factory functions that create default instances must initialize them to a usable state. An empty registry is never useful — the default should include all built-in primitives.
