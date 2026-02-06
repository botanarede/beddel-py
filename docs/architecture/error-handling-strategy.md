# Error Handling Strategy

## General Approach

- **Error Model:** Custom exception hierarchy with error codes
- **Exception Hierarchy:**
  ```
  BeddelError (base)
  ├── ParseError (YAML/validation errors)
  ├── ResolutionError (variable resolution failures)
  ├── ExecutionError (workflow execution failures)
  │   ├── PrimitiveError (primitive-specific errors)
  │   └── ProviderError (LLM provider errors)
  └── ConfigurationError (invalid configuration)
  ```
- **Error Propagation:** Errors bubble up with context; lifecycle hooks notified

## Logging Standards

- **Library:** Python `logging` (standard library)
- **Format:** JSON structured logging for production
- **Levels:** DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Required Context:**
  - Correlation ID: `workflow_id` from ExecutionContext
  - Service Context: `step_id`, `primitive_type`
  - User Context: Sanitized input (no PII)

## Error Handling Patterns

### External API Errors (LLM Providers)

- **Retry Policy:** Exponential backoff (3 attempts, 1s/2s/4s)
- **Circuit Breaker:** Not in MVP (consider for post-MVP)
- **Timeout Configuration:** Configurable per-step, default 30s
- **Error Translation:** LiteLLM errors → `ProviderError` with original context

### Business Logic Errors

- **Custom Exceptions:** `ParseError`, `ResolutionError`, `GuardrailError`
- **User-Facing Errors:** Structured JSON with error code and message
- **Error Codes:** `BEDDEL-{CATEGORY}-{NUMBER}` (e.g., `BEDDEL-PARSE-001`)

### Data Consistency

- **Transaction Strategy:** N/A (stateless execution)
- **Compensation Logic:** N/A
- **Idempotency:** Workflow executions are idempotent given same input
