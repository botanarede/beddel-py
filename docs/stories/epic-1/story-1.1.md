# Story 1.1: Project Scaffolding, CI/CD & Documentation

## Status

Draft

## Story

**As a** developer,
**I want** the project repository to have proper build configuration, CI/CD pipeline, development tooling, and README documentation,
**so that** I can install the SDK, run tests, and contribute from day one.

## Acceptance Criteria

1. `pyproject.toml` is configured with hatchling build system, project metadata, Python 3.11+ requirement, all core dependencies (pydantic, litellm, pyyaml, opentelemetry-api, httpx), dev dependencies (pytest, pytest-asyncio, pytest-cov, ruff, mypy), and optional `[fastapi]` extra
2. GitHub Actions CI workflow runs on every PR: pytest with coverage, `ruff check .`, `ruff format --check .`, `mypy src/`
3. A release workflow (manual trigger or tag-based) builds the package and publishes to PyPI via hatchling
4. README.md includes: project description, installation instructions (`pip install beddel`), quickstart code example, development setup (install dev deps, run tests, lint, type check), and contribution guidelines placeholder
5. `.gitignore` includes `.env`, `__pycache__`, `dist/`, `*.egg-info/`, `.mypy_cache/`
6. The structured error code catalog is initialized with the `BEDDEL-` prefix convention and at least the domain codes: `PARSE`, `RESOLVE`, `EXEC`, `PRIM`, `ADAPT`

## Tasks / Subtasks

- [ ] Task 1: Create `pyproject.toml` and `.gitignore` with hatchling build system (AC: 1, 5)
  - [ ] 1.0 Create `.gitignore` before any other files:
    - Python ignores: `__pycache__/`, `*.pyc`, `*.pyo`, `*.egg-info/`, `dist/`, `build/`
    - Tooling ignores: `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `htmlcov/`, `.coverage`
    - Secrets: `.env`
    - IDE ignores: `.vscode/`, `.idea/`
  - [ ] 1.1 Configure `[build-system]` with `hatchling` as build backend
  - [ ] 1.2 Set `[project]` metadata: name=`beddel`, version=`0.1.0`, description, Python `>=3.11` requirement, license, authors
  - [ ] 1.3 Add core dependencies: `pydantic>=2.0`, `litellm`, `pyyaml>=6.0`, `opentelemetry-api>=1.0`, `httpx>=0.27`
  - [ ] 1.4 Add `[project.optional-dependencies]` section:
    - `dev` = `["pytest", "pytest-asyncio", "pytest-cov", "ruff", "mypy"]`
    - `fastapi` = `["fastapi", "sse-starlette"]`
  - [ ] 1.5 Configure `[tool.ruff]` section (linting + formatting config)
  - [ ] 1.6 Configure `[tool.mypy]` section with `strict = true`
  - [ ] 1.7 Configure `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
  - [ ] 1.8 Configure hatch build targets and source paths (`src` layout: `packages = ["src/beddel"]`)

- [ ] Task 2: Create GitHub Actions CI workflow (AC: 2)
  - [ ] 2.1 Create `.github/workflows/ci.yml`
  - [ ] 2.2 Trigger on pull requests to `main` branch
  - [ ] 2.3 Set up Python 3.11+ on Ubuntu latest runner
  - [ ] 2.4 Install package with dev dependencies: `pip install -e ".[dev]"`
  - [ ] 2.5 Run `pytest --cov=beddel --cov-report=term-missing`
  - [ ] 2.6 Run `ruff check .`
  - [ ] 2.7 Run `ruff format --check .`
  - [ ] 2.8 Run `mypy src/`

- [ ] Task 3: Create GitHub Actions release workflow (AC: 3)
  - [ ] 3.1 Create `.github/workflows/release.yml`
  - [ ] 3.2 Configure trigger: manual dispatch (`workflow_dispatch`) and tag push (`v*`)
  - [ ] 3.3 Build package using `python -m build` (uses hatchling backend)
  - [ ] 3.4 Publish to PyPI using `pypa/gh-action-pypi-publish` action with trusted publisher
  - [ ] 3.5 Include a test step (pytest) before publish to prevent broken releases

- [ ] Task 4: Create README.md (AC: 4)
  - [ ] 4.1 Write project description: Beddel — declarative YAML-based AI workflow engine for Python
  - [ ] 4.2 Add installation instructions: `pip install beddel` (and `pip install beddel[fastapi]` for FastAPI extra)
  - [ ] 4.3 Add quickstart code example showing: import, load YAML workflow, execute, print results
  - [ ] 4.4 Add development setup section: clone, `pip install -e ".[dev]"`, `pytest`, `ruff check .`, `ruff format .`, `mypy src/`
  - [ ] 4.5 Add contribution guidelines placeholder section
  - [ ] 4.6 Add badges placeholder (CI status, PyPI version, Python version)

- [ ] Task 5: Initialize error code catalog and exception hierarchy (AC: 6)
  - [ ] 5.1 Create `src/beddel-py/src/beddel/__init__.py` with version constant and public API exports
  - [ ] 5.2 Create `src/beddel-py/src/beddel/domain/__init__.py`
  - [ ] 5.3 Create `src/beddel-py/src/beddel/domain/errors.py` with:
    - `BeddelError` base exception class with `code`, `message`, `details` attributes
    - `ParseError(BeddelError)` — prefix `BEDDEL-PARSE-`
    - `ResolveError(BeddelError)` — prefix `BEDDEL-RESOLVE-`
    - `ExecutionError(BeddelError)` — prefix `BEDDEL-EXEC-`
    - `PrimitiveError(BeddelError)` — prefix `BEDDEL-PRIM-`
    - `AdapterError(BeddelError)` — prefix `BEDDEL-ADAPT-`
  - [ ] 5.4 Add docstrings to all public classes with error code prefix documentation
  - [ ] 5.5 Add `__all__` export list

- [ ] Task 6: Create initial source tree skeleton
  - [ ] 6.1 Create empty `__init__.py` files for package structure:
    - `src/beddel-py/src/beddel/primitives/__init__.py`
    - `src/beddel-py/src/beddel/adapters/__init__.py`
    - `src/beddel-py/src/beddel/integrations/__init__.py`
  - [ ] 6.2 Create `src/beddel-py/src/beddel/py.typed` (empty marker file for PEP 561 typed package support)
  - [ ] 6.3 Create `src/beddel-py/tests/conftest.py` with placeholder
  - [ ] 6.4 Create `src/beddel-py/tests/domain/__init__.py`

- [ ] Task 7: Write unit tests for error catalog (AC: 6)
  - [ ] 7.1 Create `src/beddel-py/tests/domain/test_errors.py`
  - [ ] 7.2 Test `BeddelError` instantiation with code, message, details
  - [ ] 7.3 Test each subclass (`ParseError`, `ResolveError`, `ExecutionError`, `PrimitiveError`, `AdapterError`) inherits from `BeddelError`
  - [ ] 7.4 Test `str()` representation includes error code and message
  - [ ] 7.5 Test `details` defaults to empty dict when not provided

## Dev Notes

### Hatchling Path Note

The `pyproject.toml` lives at `src/beddel-py/pyproject.toml`. Hatch build source should point to `src/beddel` relative to that location. Verify the `[tool.hatch.build.targets.wheel]` `packages` path resolves correctly with `hatch build` after Task 1.

### Source Tree Structure

The Python SDK lives under `src/beddel-py/` with a `src` layout. This story creates the skeleton:

```
src/
└── beddel-py/
    ├── pyproject.toml
    ├── src/
    │   └── beddel/
    │       ├── __init__.py          # Public API exports, version
    │       ├── py.typed             # PEP 561 typed package marker
    │       ├── domain/
    │       │   ├── __init__.py
    │       │   └── errors.py        # BeddelError + error code catalog
    │       ├── primitives/
    │       │   └── __init__.py      # Empty (populated in Story 1.4)
    │       ├── adapters/
    │       │   └── __init__.py      # Empty (populated in Story 1.5)
    │       └── integrations/
    │           └── __init__.py      # Empty (populated in Epic 3)
    └── tests/
        ├── conftest.py
        └── domain/
            ├── __init__.py
            └── test_errors.py
```

[Source: docs/architecture/12-source-tree.md]

### Tech Stack Details

| Category | Technology | Version | Notes |
|----------|-----------|---------|-------|
| Language | Python | 3.11+ | Modern async, typing, performance |
| Build System | hatchling | latest | PEP 517 compliant |
| Validation | Pydantic | 2.x | Schema validation, data models |
| LLM Abstraction | LiteLLM | latest | 100+ providers |
| YAML Parsing | PyYAML | 6.x | `safe_load` only |
| Observability | opentelemetry-api | 1.x | Distributed tracing |
| HTTP Client | httpx | 0.27+ | Async HTTP |
| Testing | pytest + pytest-asyncio | latest | Async test support |
| Coverage | pytest-cov | latest | >80% domain coverage target |
| Linting + Formatting | ruff | latest | Single tool, replaces black + flake8 + isort |
| Type Checking | mypy | latest (strict) | Strict mode for SDK quality |
| Web Framework | FastAPI | latest | Optional `[fastapi]` extra |
| SSE | sse-starlette | latest | FastAPI-compatible SSE |
| CI/CD | GitHub Actions | N/A | PR checks + PyPI publish |

[Source: docs/architecture/3-tech-stack.md#32-technology-stack-table]

### Coding Standards

- **Style & Linting:** `ruff` for both linting and formatting. Configuration in `pyproject.toml`. No separate black/flake8/isort.
- **Type Checking:** `mypy` in strict mode. All public functions and methods must have complete type annotations.
- **Naming Conventions:**
  - Files (modules): `snake_case.py` (e.g., `litellm_adapter.py`)
  - Classes: `PascalCase` (e.g., `BeddelError`)
  - Functions/Methods: `snake_case` (e.g., `register_namespace`)
  - Constants: `SCREAMING_SNAKE_CASE` (e.g., `BEDDEL_VERSION`)
  - Private members: `_leading_underscore`
- **Domain isolation:** Domain core (`domain/`) MUST NOT import from `adapters/`, `integrations/`, or any third-party library except `pydantic` and `pyyaml` (NFR10).
- **Docstrings required:** 100% of public API functions and classes MUST have docstrings (NFR13).
- **Structured errors:** All errors raised by the SDK MUST be `BeddelError` subclasses with proper `BEDDEL-*` error codes (NFR15).
- **No hardcoded limits:** All limits and thresholds MUST be configurable with sensible defaults (NFR11).
- **Public naming for cross-module functions:** If a function is imported across module boundaries, it MUST be public (no underscore prefix). Add it to `__all__` (lesson §13.7).

[Source: docs/architecture/15-coding-standards.md]

### Error Handling Strategy

The SDK uses structured error codes with `BEDDEL-` prefix. Every error carries a code, human-readable message, and optional details dict.

**Exception Hierarchy:**
```
BeddelError (base)
├── ParseError        (BEDDEL-PARSE-*)
├── ResolveError      (BEDDEL-RESOLVE-*)
├── ExecutionError    (BEDDEL-EXEC-*)
├── PrimitiveError    (BEDDEL-PRIM-*)
└── AdapterError      (BEDDEL-ADAPT-*)
```

**BeddelError base class:**
```python
class BeddelError(Exception):
    """Base error with structured error code."""
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code          # e.g., "BEDDEL-EXEC-001"
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")
```

**Domain error codes:**

| Prefix | Domain | Examples |
|--------|--------|----------|
| `BEDDEL-PARSE-` | YAML parsing & validation | `BEDDEL-PARSE-001`: Invalid YAML syntax |
| `BEDDEL-RESOLVE-` | Variable resolution | `BEDDEL-RESOLVE-001`: Unresolvable variable |
| `BEDDEL-EXEC-` | Workflow execution | `BEDDEL-EXEC-001`: Missing metadata key |
| `BEDDEL-PRIM-` | Primitive execution | `BEDDEL-PRIM-001`: Primitive not found |
| `BEDDEL-ADAPT-` | Adapter errors | `BEDDEL-ADAPT-001`: Provider authentication failure |

[Source: docs/architecture/14-error-handling-strategy.md, docs/architecture/4-data-models.md#46-beddelerror]

### CI/CD Pipeline Details

- **CI Platform:** GitHub Actions
- **CI Trigger:** Pull requests to `main`
- **CI Steps:** pytest with coverage → ruff check → ruff format --check → mypy src/
- **Release Strategy:** PyPI package distribution via hatchling build
- **Release Trigger:** Manual dispatch (`workflow_dispatch`) or tag push (`v*`)
- **Release Pipeline:** `.github/workflows/ci.yml` (PR checks), `.github/workflows/release.yml` (PyPI publish)
- **Environments:**
  - Development: Local virtualenv with `pip install -e ".[dev]"`
  - CI: GitHub Actions runners (Ubuntu latest, Python 3.11+)
  - Production: PyPI package installed by end users
- **Promotion Flow:** Local Development → PR (CI checks) → main branch → Tag release → PyPI publish
- **Rollback:** PyPI version yanking + new patch release (< 1 hour RTO)

[Source: docs/architecture/13-infrastructure-and-deployment.md]

### Security Requirements

- **YAML Safety:** `yaml.safe_load()` exclusively — no `yaml.load()`, no `eval()`, no dynamic code execution (NFR7). CI check to ensure no `yaml.load()` calls exist in the codebase.
- **Secrets:** API keys via environment variables only — never hardcoded (NFR8). `.gitignore` MUST include `.env`.
- **Logging:** Never log API keys, secrets, or full LLM responses. Log only: workflow ID, step ID, model name, token counts, error codes.
- **Dependencies:** GitHub Dependabot for automatic scanning. Core dependencies pinned with minimum versions in `pyproject.toml`.

[Source: docs/architecture/17-security.md]

### Lessons Learned Relevant to Story 1.1

- **§13.2 / §13.11 — Factory defaults:** Factory functions MUST produce usable instances. Empty registries or missing providers are never acceptable defaults. When creating `pyproject.toml`, ensure all core dependencies are included so the SDK is installable and functional from day one. [Source: docs/brief.md#13.2, docs/brief.md#13.11]
- **§13.4 — Stable model names:** Example workflows and README quickstart MUST use stable model names only (never `-exp` suffixes). Add comments noting model names may need updating. [Source: docs/brief.md#13.4]
- **§13.7 — Public naming:** Cross-module functions must be public (no underscore prefix) and added to `__all__`. Apply this from the start in `errors.py`. [Source: docs/brief.md#13.7]

### Testing

**Test Framework:** pytest + pytest-asyncio
**Test Location:** `src/beddel-py/tests/` — mirrors source structure
**File Convention:** `test_<module>.py` in `tests/<layer>/`
**Coverage Tool:** pytest-cov — target >80% on domain logic
**Test Pattern:** AAA (Arrange, Act, Assert)

**For this story specifically:**
- Unit tests for error catalog in `tests/domain/test_errors.py`
- Test all public classes: `BeddelError`, `ParseError`, `ResolveError`, `ExecutionError`, `PrimitiveError`, `AdapterError`
- Test instantiation, inheritance, string representation, default details
- Mock all external dependencies via port interfaces (not applicable for this story — errors module has no external deps)

**CI Integration:**
- `pytest --cov=beddel --cov-report=term-missing`
- `ruff check .`
- `ruff format --check .`
- `mypy src/`

[Source: docs/architecture/16-test-strategy-and-standards.md]

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-02-11 | 1.0 | Initial story draft | Bob (SM) |
| 2026-02-11 | 1.1 | PO validation: merged .gitignore into Task 1, renumbered tasks 5-7, added hatchling path note, added py.typed to Task 6 | Sarah (PO) |

## Dev Agent Record

### Agent Model Used

_To be filled during implementation_

### Debug Log References

_To be filled during implementation_

### Completion Notes List

_To be filled during implementation_

### File List

_To be filled during implementation_

## QA Results

_To be filled during QA review_
