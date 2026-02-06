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

## on_error Hook Firing Rules

| Exception Type | Step-level `on_error` | Workflow-level `on_error` | Behavior |
|---|---|---|---|
| `ExecutionError` / `PrimitiveError` | ✅ fires | ✅ fires (re-raised) | Domain errors propagate up after notifying hooks |
| Generic `Exception` | ✅ fires | ❌ (handled at step) | Converted to `StepResult(success=False)` |

## Skip Strategy Semantics

When a step has `on_error: { strategy: skip }` and fails:

- `StepResult.success` is `False` (the step did not succeed)
- The workflow **continues** to the next step
- The skipped step does **not** write to `context.step_results`
- If a later step or `return` template references `$stepResult.<skipped_key>`, it will raise `ResolutionError` (fail-fast by design)
- Workflow authors should guard dependent steps with `condition` checks or avoid referencing skippable results in `return` templates

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

- **Retry Policy:** Not in MVP. Primitives may implement their own retry logic.
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
