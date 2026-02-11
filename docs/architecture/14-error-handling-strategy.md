# 14. Error Handling Strategy

## 14.1 General Approach

- **Error Model:** Structured error codes with `BEDDEL-` prefix. Every error carries a code, human-readable message, and optional details dict. See §4.6 for `BeddelError` definition.
- **Exception Hierarchy:**
  ```
  BeddelError (base)
  ├── ParseError        (BEDDEL-PARSE-*)
  ├── ResolveError      (BEDDEL-RESOLVE-*)
  ├── ExecutionError    (BEDDEL-EXEC-*)
  ├── PrimitiveError    (BEDDEL-PRIM-*)
  └── AdapterError      (BEDDEL-ADAPT-*)
  ```
- **Error Propagation:** Errors bubble up through the execution stack. The executor catches errors at the step level and applies the step's execution strategy (fail, skip, retry, fallback). Unhandled errors propagate to the caller as `BeddelError` with full context.

## 14.2 Logging Standards

- **Library:** Python `logging` (stdlib)
- **Format:** Structured JSON logging recommended for production; human-readable for development
- **Levels:**
  - `DEBUG`: Variable resolution details, step config after resolution
  - `INFO`: Workflow start/end, step start/end
  - `WARNING`: Retry attempts, fallback activation, deprecated model names
  - `ERROR`: Step failures, adapter errors, missing metadata keys
  - `CRITICAL`: Unrecoverable errors (should be rare in an SDK)
- **Required Context:**
  - Workflow ID in every log message during execution
  - Step ID in step-level log messages
  - Error code in all error log messages
- **Security:** Never log API keys, secrets, or full LLM responses (may contain PII). Log model name and token counts only.

## 14.3 Error Handling Patterns

### External API Errors (LLM Providers)

- **Retry Policy:** Configurable per step via `ExecutionStrategy`. Default: 3 attempts, exponential backoff (base 2s, max 60s), jitter enabled. Retries only on transient errors (HTTP 429, 500, 502, 503, 504, connection errors).
- **Circuit Breaker:** Planned for Epic 4. Provider-level circuit breaker with configurable failure thresholds and recovery windows.
- **Timeout Configuration:** Step-level timeout via `step.timeout` (seconds). Default: no timeout (LLM provider timeout applies). Timeout triggers the step's execution strategy.
- **Error Translation:** `LiteLLMAdapter` catches LiteLLM exceptions and translates them to `BeddelError` with `BEDDEL-ADAPT-*` codes. Provider-specific error details preserved in `error.details`.

### Business Logic Errors

- **Custom Exceptions:** Domain-specific subclasses of `BeddelError` (see hierarchy above).
- **User-Facing Errors:** All errors include the error code and a human-readable message. The `details` dict provides machine-readable context for programmatic handling.
- **Error Codes:** Documented in the error catalog (see §4.6). Each code has a documented meaning, likely cause, and suggested resolution.

### Data Consistency

N/A — Beddel is stateless. No transactions, no compensation logic. State persistence (Epic 5) will introduce checkpoint-based consistency.

---
