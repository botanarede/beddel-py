# Security

## Input Validation

- **Validation Library:** Pydantic 2.x
- **Validation Location:** Parser (YAML → models), Guardrail primitive
- **Required Rules:**
  - All YAML input MUST be validated via Pydantic models
  - `yaml.safe_load()` ONLY - never `yaml.load()`
  - Guardrail primitive validates LLM inputs/outputs

## Authentication & Authorization

- **Auth Method:** N/A (SDK delegates to user application)
- **Session Management:** N/A
- **Required Patterns:**
  - API keys passed via environment variables
  - No credential storage within Beddel

## Secrets Management

- **Development:** `.env` files (gitignored)
- **Production:** User's secret management (AWS Secrets Manager, Vault, etc.)
- **Code Requirements:**
  - NEVER hardcode API keys or secrets
  - Access via `os.getenv()` only
  - No secrets in logs or error messages

## API Security

- **Rate Limiting:** Delegated to user's FastAPI middleware
- **CORS Policy:** Delegated to user's FastAPI configuration
- **Security Headers:** Delegated to user's deployment
- **HTTPS Enforcement:** Delegated to user's infrastructure

## Data Protection

- **Encryption at Rest:** N/A (stateless)
- **Encryption in Transit:** HTTPS enforced by LLM providers
- **PII Handling:** Guardrail primitive can validate/redact PII
- **Logging Restrictions:** No raw LLM inputs/outputs in logs by default

## Dependency Security

- **Scanning Tool:** `pip-audit` in CI
- **Update Policy:** Monthly dependency updates, immediate for security patches
- **Approval Process:** Dependabot PRs reviewed before merge

## Security Testing

- **SAST Tool:** `bandit` for Python security linting
- **DAST Tool:** N/A (SDK, not deployed service)
- **Penetration Testing:** N/A
