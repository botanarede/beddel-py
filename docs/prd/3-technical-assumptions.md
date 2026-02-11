# 3. Technical Assumptions

## 3.1 Repository Structure: Monorepo

The project uses a monorepo structure with `spec/` at the root (shared cross-SDK fixtures) and `src/beddel-py/` for the Python SDK. This enables future multi-language SDKs to share the same behavioral specification.

```
beddel/
├── spec/                      # Shared specification (JSON Schema, fixtures)
│   ├── schemas/               # JSON Schema definitions
│   ├── fixtures/              # YAML test fixtures (valid/, invalid/, expected/)
│   └── tests/                 # Cross-SDK test files
├── src/
│   └── beddel-py/             # Python SDK
│       ├── src/beddel/
│       │   ├── domain/        # Core: parser, resolver, executor, registry, models, ports
│       │   ├── primitives/    # llm, chat, output-generator, call-agent, guardrail, tool
│       │   ├── adapters/      # LiteLLM, OpenTelemetry, Memory, PII
│       │   └── integrations/  # FastAPI, SSE
│       └── tests/
├── docs/
└── .bmad-core/
```

## 3.2 Service Architecture

Hexagonal Architecture (Ports & Adapters) — a framework-agnostic Python SDK, not a web application. The domain core defines abstract port interfaces; adapters implement them for specific external services. FastAPI integration is an optional extra, not a core dependency.

## 3.3 Testing Requirements

Full testing pyramid:
- **Unit tests:** Domain logic (parser, resolver, executor, registry) with > 80% coverage
- **Integration tests:** Port-to-adapter wiring verification — every port interface must have a test proving the adapter reaches the primitive through the full execution path
- **Spec fixture tests:** Cross-SDK behavioral validation using shared YAML fixtures
- **CI enforcement:** All tests, lint, type checks, and format checks run on every PR via GitHub Actions

## 3.4 Additional Technical Assumptions

- Python 3.11+ is required — leverages modern async, typing, and performance features
- `asyncio` with `async/await` is the async runtime — no third-party event loops
- Pydantic 2.x is stable and performant enough for runtime validation on every step
- LiteLLM is the multi-provider abstraction layer; adapter pattern absorbs breaking changes
- `hatchling` is the build system (PEP 517 compliant)
- `ruff` handles both linting and formatting (single tool, replaces black + flake8 + isort)
- `mypy` in strict mode for static type checking
- All configuration via environment variables — no config files for secrets
- Streaming is an execution-level concern owned by the executor, not a response format adapter
- The ExecutionContext Wiring Contract must be documented and enforced before Epic 2 primitives depend on metadata keys

---
