# 15. Coding Standards

## 15.1 Core Standards

- **Language & Runtime:** Python 3.11+ with `asyncio`. All public APIs are async.
- **Style & Linting:** `ruff` for both linting and formatting. Configuration in `pyproject.toml`. No separate black/flake8/isort.
- **Type Checking:** `mypy` in strict mode. All public functions and methods must have complete type annotations.
- **Test Organization:** Tests mirror source structure under `tests/`. Test files named `test_<module>.py`. Integration tests in `tests/integration/`.

## 15.2 Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Files (modules) | `snake_case.py` | `litellm_adapter.py`, `call_agent.py` |
| Classes | `PascalCase` | `WorkflowExecutor`, `LiteLLMAdapter` |
| Functions / Methods | `snake_case` | `execute_stream`, `register_namespace` |
| Constants | `SCREAMING_SNAKE_CASE` | `DEFAULT_MAX_RETRIES`, `BEDDEL_VERSION` |
| Private members | `_leading_underscore` | `_build_params`, `_evaluate_condition` |
| Type aliases | `PascalCase` | `StepResult`, `NamespaceHandler` |

## 15.3 Critical Rules

- **Domain isolation:** Domain core (`domain/`) MUST NOT import from `adapters/`, `integrations/`, or any third-party library except `pydantic` and `pyyaml`. Violation of this rule breaks the hexagonal architecture (NFR10).
- **Public naming for cross-module functions:** If a function is imported across module boundaries, it MUST be public (no underscore prefix). Add it to `__all__` (lesson §13.7).
- **yaml.safe_load() only:** Never use `yaml.load()`, `eval()`, or any dynamic code execution. Security requirement (NFR7).
- **Explicit API key resolution:** Adapters MUST explicitly resolve API keys from environment variables. Never rely solely on third-party library auto-detection (lesson §13.3).
- **Factory defaults:** Factory functions MUST produce usable instances. Empty registries or missing providers are never acceptable defaults (lessons §13.2, §13.11).
- **Stable model names:** Example code and fixtures MUST use stable model names only. Never use experimental `-exp` suffixes (lesson §13.4).
- **Docstrings required:** 100% of public API functions and classes MUST have docstrings (NFR13).
- **Structured errors:** All errors raised by the SDK MUST be `BeddelError` subclasses with proper `BEDDEL-*` error codes (NFR15).
- **No hardcoded limits:** All limits and thresholds MUST be configurable with sensible defaults (NFR11).

## 15.4 Python-Specific Guidelines

- **Async patterns:** Use `async def` for all I/O-bound operations. Use `AsyncGenerator` for streaming. Never mix sync and async in the same call path.
- **Pydantic models:** Use `BaseModel` with `Field()` for all data structures. Use `model_config = ConfigDict(...)` for model configuration. Use `model_validator` for cross-field validation.
- **Imports:** Use absolute imports within the package (`from beddel.domain.models import Workflow`). Relative imports only within the same subpackage.
- **Error handling:** Catch specific exceptions, never bare `except:`. Always re-raise as `BeddelError` with appropriate error code.

---
