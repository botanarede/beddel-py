# Coding Standards

## Core Standards

- **Languages & Runtimes:** Python 3.11+ (3.12 recommended)
- **Style & Linting:** Ruff with default rules + type checking via mypy
- **Test Organization:** `tests/unit/`, `tests/integration/`, mirror src structure

## Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Modules | snake_case | `variable_resolver.py` |
| Classes | PascalCase | `WorkflowExecutor` |
| Functions | snake_case | `resolve_variables()` |
| Constants | SCREAMING_SNAKE | `DEFAULT_TIMEOUT` |
| Type Aliases | PascalCase | `StepResult = dict[str, Any]` |

## Critical Rules

- **YAML Security:** NEVER use `yaml.load()` - ONLY `yaml.safe_load()`. _Rationale:_ Prevents arbitrary code execution from malicious YAML.

- **Async Consistency:** All I/O functions MUST be async. Sync wrappers use `asyncio.run()`. _Rationale:_ Prevents blocking the event loop.

- **Pydantic Models:** All external data MUST pass through Pydantic validation before use. _Rationale:_ Ensures type safety and catches errors early.

- **No Secrets in Code:** API keys MUST come from environment variables via `os.getenv()`. _Rationale:_ Security requirement NFR8.

- **Structured Logging:** Use `logger.info("message", extra={...})` not f-strings with data. _Rationale:_ Enables log aggregation and prevents PII leaks.

- **Type Hints Required:** All public functions MUST have complete type hints. _Rationale:_ Enables mypy checking and IDE support.
