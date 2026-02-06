# Tech Stack

## Cloud Infrastructure

- **Provider:** Cloud-agnostic (user's choice)
- **Key Services:** N/A (SDK runs in user's infrastructure)
- **Deployment Regions:** N/A

## Technology Stack Table

| Category | Technology | Version | Purpose | Rationale |
|----------|------------|---------|---------|-----------|
| **Language** | Python | 3.11+ | Primary development language | Async support, type hints, target audience |
| **Type Checking** | mypy | 1.14+ | Static type analysis | Catch errors early, improve IDE support |
| **Validation** | Pydantic | 2.10+ | Schema validation, structured outputs | Industry standard, excellent performance |
| **LLM Abstraction** | LiteLLM | 1.55+ | Multi-provider LLM interface | 100+ providers, unified API |
| **YAML Parsing** | PyYAML | 6.0+ | Workflow definition parsing | Standard library, safe_load support |
| **HTTP Client** | httpx | 0.28+ | Async HTTP requests | Modern async client, HTTP/2 support |
| **Observability** | opentelemetry-api | 1.29+ | Distributed tracing | Industry standard, vendor-neutral |
| **Observability SDK** | opentelemetry-sdk | 1.29+ | Tracing implementation | Required for span generation |
| **Web Framework** | FastAPI | 0.115+ | SSE streaming integration | Async-native, excellent performance |
| **ASGI Server** | uvicorn | 0.34+ | Development server | FastAPI recommended server |
| **Testing** | pytest | 8.3+ | Test framework | Industry standard, excellent plugins |
| **Async Testing** | pytest-asyncio | 0.25+ | Async test support | Required for async test fixtures |
| **Linting** | Ruff | 0.9+ | Linting and formatting | Fast, replaces flake8/black/isort |
| **Build** | hatchling | 1.27+ | Package building | Modern, PEP 517 compliant |

> **Note:** FastAPI and uvicorn are optional dependencies, installed via `pip install beddel[fastapi]`. The core SDK is framework-agnostic.
