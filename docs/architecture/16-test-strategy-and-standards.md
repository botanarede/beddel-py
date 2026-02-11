# 16. Test Strategy and Standards

## 16.1 Testing Philosophy

- **Approach:** Test-after for initial implementation, with spec fixtures as the behavioral contract. Integration tests are mandatory for port/adapter wiring (lesson §13.1).
- **Coverage Goals:** > 80% on domain logic (`domain/`), measured by `pytest-cov`. Primitives and adapters tested via integration tests.
- **Test Pyramid:**
  - Unit tests (60%): Domain logic — parser, resolver, executor, registry
  - Integration tests (30%): Port-to-adapter wiring, factory defaults, full execution paths
  - Spec fixture tests (10%): Cross-SDK behavioral validation using shared YAML fixtures

## 16.2 Test Types and Organization

### Unit Tests

- **Framework:** pytest + pytest-asyncio
- **File Convention:** `test_<module>.py` in `tests/<layer>/`
- **Location:** `src/beddel-py/tests/domain/`, `tests/primitives/`
- **Mocking:** `unittest.mock` (stdlib) — mock port interfaces for primitive tests
- **Coverage Requirement:** > 80% on `domain/`

**AI Agent Requirements:**
- Generate tests for all public methods
- Cover edge cases: empty inputs, missing fields, circular references, timeout expiry
- Follow AAA pattern (Arrange, Act, Assert)
- Mock all external dependencies via port interfaces
- Test both success and error paths for every execution strategy

### Integration Tests

- **Scope:** Full wiring path verification — factory → executor → context → primitive → adapter
- **Location:** `src/beddel-py/tests/integration/`
- **Test Infrastructure:**
  - **LLM Provider:** Mock `ILLMProvider` implementation (no real API calls in CI)
  - **FastAPI:** `httpx.AsyncClient` with `TestClient` for HTTP endpoint tests
  - **SSE:** Validate multi-line data serialization with realistic payloads (lesson §13.8)

**Critical Integration Tests (lesson §13.1):**
1. `test_wiring.py`: Verify `LiteLLMAdapter` reaches `llm` primitive through full execution path
2. `test_factory_defaults.py`: Verify `create_beddel_handler()` produces working defaults
3. `test_metadata_injection.py`: Verify all wiring contract keys are present in `ExecutionContext.metadata`

### Spec Fixture Tests

- **Framework:** pytest loading YAML fixtures from `spec/fixtures/`
- **Scope:** Behavioral validation — parse valid/invalid workflows, verify expected execution results
- **Location:** `spec/tests/`
- **Data:** `spec/fixtures/valid/`, `spec/fixtures/invalid/`, `spec/fixtures/expected/`

## 16.3 Test Data Management

- **Strategy:** YAML fixtures in `spec/fixtures/` are the single source of truth (NFR4)
- **Fixtures:** `spec/fixtures/valid/`, `spec/fixtures/invalid/`, `spec/fixtures/expected/`
- **Factories:** `conftest.py` provides factory functions for `Workflow`, `Step`, `ExecutionContext` with sensible defaults
- **Cleanup:** No persistent state — all tests are stateless and isolated

## 16.4 Continuous Testing

- **CI Integration:** GitHub Actions runs on every PR:
  1. `pytest --cov=beddel --cov-report=term-missing` (tests + coverage)
  2. `ruff check .` (lint)
  3. `ruff format --check .` (format)
  4. `mypy src/` (type check)
- **Performance Tests:** Execution overhead benchmark (< 5ms per step, NFR1) — manual for MVP, automated in CI post-MVP
- **Security Tests:** `yaml.safe_load()` enforcement verified by grep/AST check in CI. No SAST/DAST for MVP (SDK, not service).

---
