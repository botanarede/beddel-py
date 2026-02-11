# 3. Tech Stack

## 3.1 Cloud Infrastructure

N/A — Beddel is a Python SDK distributed via PyPI. It has no cloud infrastructure of its own. Users deploy it within their own infrastructure. CI/CD runs on GitHub Actions.

## 3.2 Technology Stack Table

| Category | Technology | Version | Purpose | Rationale |
|----------|-----------|---------|---------|-----------|
| **Language** | Python | 3.11+ | Primary development language | Modern async, typing, performance; target audience (AI/ML) is on 3.11+ |
| **Async Runtime** | asyncio | stdlib | Async execution engine | Standard library, no third-party event loop dependency |
| **Validation** | Pydantic | 2.x | Schema validation, data models, structured output | Industry standard for Python data validation; fast V2 engine |
| **LLM Abstraction** | LiteLLM | latest | Multi-provider LLM calls (100+ providers) | Eliminates provider lock-in; adapter pattern absorbs breaking changes |
| **YAML Parsing** | PyYAML | 6.x | Workflow definition parsing | Mature, `safe_load` for security; universal YAML support |
| **Observability** | opentelemetry-api | 1.x | Distributed tracing, span generation | Industry standard; vendor-neutral observability |
| **HTTP Client** | httpx | 0.27+ | Async HTTP requests | Modern async-first HTTP client; used by LiteLLM internally |
| **Build System** | hatchling | latest | Package building (PEP 517) | Modern, fast, standards-compliant Python build backend |
| **Testing** | pytest | latest | Test framework | De facto Python testing standard |
| **Testing (async)** | pytest-asyncio | latest | Async test support | Required for testing async primitives and executor |
| **Coverage** | pytest-cov | latest | Code coverage reporting | Enforces >80% domain coverage target (NFR3) |
| **Linting + Formatting** | ruff | latest | Lint and format (replaces black + flake8 + isort) | Single tool, extremely fast, comprehensive rule set |
| **Type Checking** | mypy | latest (strict) | Static type analysis | Catches type errors before runtime; strict mode for SDK quality |
| **Web Framework** | FastAPI | latest | Optional HTTP integration (`[fastapi]` extra) | High-performance async framework; Pydantic-native |
| **SSE** | sse-starlette | latest | Server-Sent Events streaming | FastAPI-compatible SSE support |
| **CI/CD** | GitHub Actions | N/A | Continuous integration and deployment | Free for open source; native GitHub integration |
| **Package Registry** | PyPI | N/A | Package distribution | Standard Python package distribution |

---
