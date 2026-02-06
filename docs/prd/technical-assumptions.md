# Technical Assumptions

## Platform Requirements

| Requirement | Specification |
|-------------|---------------|
| Python Version | 3.11+ required, 3.12 recommended |
| Framework | Framework-agnostic core; FastAPI 0.115+ via `[fastapi]` extra |
| Async Runtime | `asyncio` with `async/await` patterns |

## Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic` | 2.x | Schema validation, structured outputs |
| `litellm` | latest | Multi-provider LLM abstraction |
| `pyyaml` | 6.x | YAML parsing (safe_load only) |
| `opentelemetry-api` | 1.x | Observability spans |
| `httpx` | 0.27+ | Async HTTP client |

## Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | 8.3+ | Testing with async fixtures |
| `pytest-asyncio` | 0.24+ | Async test support |
| `ruff` | 0.8+ | Linting and formatting |
| `mypy` | 1.x | Static type checking |

## Architecture Assumptions

1. **Hexagonal Architecture:** Domain logic isolated from adapters (LLM, storage)
2. **Async-First:** All I/O operations are async; sync wrappers provided for compatibility
3. **Immutable Configuration:** Workflow YAML parsed once, executed multiple times
4. **Stateless Execution:** Each workflow execution is independent (state via callbacks)

## Integration Assumptions

| Integration | Protocol | Notes |
|-------------|----------|-------|
| LLM Providers | LiteLLM SDK | Unified interface for 100+ providers |
| External Tools | MCP (Model Context Protocol) | Post-MVP; basic function tools in MVP |
| Observability | OpenTelemetry (OTLP) | LangSmith/Jaeger/etc. compatible |
| Web Framework | FastAPI SSE (optional) | Via `beddel[fastapi]` extra |

## Constraints

| Constraint | Description |
|------------|-------------|
| Budget | Solo developer / small team |
| Timeline | MVP in 4-6 weeks (5 Epics) |
| Compatibility | 100% YAML parity with beddel-ts |
| Security | No `yaml.load()`, env-only secrets |

## Key Assumptions

- Python 3.11+ adoption is sufficient for target AI developer audience
- LiteLLM maintains backward compatibility and provider coverage
- Developers prefer YAML over Python for simple workflow definitions
- Framework integrations are optional extras; core SDK is framework-agnostic
- FastAPI + SSE available via `beddel[fastapi]` for web applications
