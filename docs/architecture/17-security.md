# 17. Security

## 17.1 Input Validation

- **Validation Library:** Pydantic 2.x
- **Validation Location:** At the parser boundary — all YAML input is validated into Pydantic models before any execution occurs
- **Required Rules:**
  - All YAML input MUST be parsed with `yaml.safe_load()` exclusively (NFR7)
  - No `yaml.load()`, no `eval()`, no `exec()`, no dynamic code execution
  - Pydantic models reject unknown fields and invalid types at parse time
  - Variable references are validated during resolution (no arbitrary code injection)

## 17.2 Authentication & Authorization

N/A — Beddel is an SDK, not a service. Authentication is delegated to LLM providers via API keys. The SDK does not manage user sessions or authorization.

**API Key Handling:**
- API keys are provided via environment variables only (NFR8)
- The `LiteLLMAdapter` explicitly resolves keys from well-known env vars (lesson §13.3):
  - `OPENAI_API_KEY` for OpenAI models
  - `GEMINI_API_KEY` for Google Gemini models
  - `ANTHROPIC_API_KEY` for Anthropic models
  - `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` for AWS Bedrock
- Keys are never logged, never included in error messages, never stored in workflow YAML

## 17.3 Secrets Management

- **Development:** `.env` file (gitignored) with API keys
- **Production:** User's own secrets management (env vars, vault, cloud secrets manager)
- **Code Requirements:**
  - NEVER hardcode secrets in source code or YAML files
  - Access API keys via `os.environ` in the adapter layer only
  - No secrets in logs, error messages, or tracebacks
  - `.gitignore` MUST include `.env`

## 17.4 API Security

N/A for the SDK itself. When used with FastAPI integration:
- Rate limiting is the user's responsibility (FastAPI middleware)
- CORS configuration is the user's responsibility
- HTTPS enforcement is the user's responsibility
- The SDK provides no security middleware — it's a library, not a framework

## 17.5 Data Protection

- **Encryption at Rest:** N/A — stateless SDK
- **Encryption in Transit:** HTTPS enforced by LLM provider SDKs (via httpx/LiteLLM)
- **PII Handling:** PII tokenization planned for Epic 5. For MVP, users are responsible for PII handling before passing data to workflows
- **Logging Restrictions:** Never log full LLM responses (may contain PII), API keys, or user input data. Log only: workflow ID, step ID, model name, token counts, error codes

## 17.6 Dependency Security

- **Scanning Tool:** GitHub Dependabot (automatic for GitHub repos)
- **Update Policy:** Monthly dependency updates; immediate updates for security advisories
- **Approval Process:** All dependency additions require justification. Core dependencies are pinned with minimum versions in `pyproject.toml`. LiteLLM version pinned due to API key resolution behavior (lesson §13.3).

## 17.7 Security Testing

- **SAST Tool:** `ruff` security rules + `mypy` strict mode (catches type-related security issues)
- **DAST Tool:** N/A — SDK, not a deployed service
- **Penetration Testing:** N/A for MVP
- **YAML Safety:** CI check to ensure no `yaml.load()` calls exist in the codebase (grep-based or AST-based)

---
