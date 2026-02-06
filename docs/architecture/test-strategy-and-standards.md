# Test Strategy and Standards

## Testing Philosophy

- **Approach:** Test-after with high coverage targets
- **Coverage Goals:** >80% for domain logic, >60% overall
- **Test Pyramid:** 70% unit, 25% integration, 5% E2E

## Test Types and Organization

### Unit Tests

- **Framework:** pytest 8.3+
- **File Convention:** `test_{module}.py`
- **Location:** `tests/unit/`
- **Mocking Library:** `unittest.mock` + `pytest-mock`
- **Coverage Requirement:** >80% for domain/

**AI Agent Requirements:**
- Generate tests for all public methods
- Cover edge cases and error conditions
- Follow AAA pattern (Arrange, Act, Assert)
- Mock all external dependencies (LiteLLM, file I/O)

### Integration Tests

- **Scope:** Adapter integrations, framework endpoints (when extras installed)
- **Location:** `tests/integration/`
- **Test Infrastructure:**
  - **LLM Providers:** Mock responses via `respx` or `pytest-httpx`
  - **FastAPI:** `TestClient` from Starlette (requires `beddel[fastapi]`)

### E2E Tests

- **Framework:** pytest with real (sandboxed) LLM calls
- **Scope:** Full workflow execution with test API keys
- **Environment:** CI with secrets, manual trigger only
- **Test Data:** Fixtures in `tests/fixtures/workflows/`

## Test Data Management

- **Strategy:** YAML fixtures shared with other SDKs
- **Fixtures:** `tests/fixtures/` and `spec/fixtures/`
- **Factories:** Pydantic model factories via `pydantic-factories`
- **Cleanup:** N/A (stateless tests)

## Continuous Testing

- **CI Integration:** GitHub Actions on PR and push to main
- **Performance Tests:** Manual benchmarks (post-MVP)
- **Security Tests:** `bandit` for SAST, dependency scanning via `pip-audit`
