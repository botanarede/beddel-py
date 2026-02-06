# Requirements

## Functional Requirements

### Core Engine

| ID | Requirement | Priority |
|----|-------------|----------|
| FR1 | Parse YAML workflow files using `yaml.safe_load()` with Pydantic validation | P0 |
| FR2 | Resolve variables with patterns: `$input.*`, `$stepResult.*`, `$env.*` (recursive resolution) | P0 |
| FR3 | Execute workflow steps asynchronously with sequential ordering and early-return for streaming | P0 |
| FR4 | Provide extensible `PrimitiveRegistry` with decorator-based registration | P0 |
| FR4.1 | Support optional `return` template for explicit API response contract definition | P0 |

### Primitives

| ID | Requirement | Priority |
|----|-------------|----------|
| FR5 | Implement `llm` primitive for single-turn LLM calls with structured output support | P0 |
| FR6 | Implement `chat` primitive for multi-turn conversational interactions | P0 |
| FR7 | Implement `output-generator` primitive for template-based output generation | P0 |
| FR8 | Implement `call-agent` primitive for nested workflow invocation | P0 |
| FR9 | Implement `guardrail` primitive for input/output validation with Pydantic schemas | P0 |
| FR10 | Implement `tool` primitive for function invocation (basic; full MCP post-MVP) | P1 |

### Provider Support (via LiteLLM)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR11 | Support OpenRouter provider via LiteLLM unified interface | P0 |
| FR12 | Support Google Gemini provider via LiteLLM | P0 |
| FR13 | Support AWS Bedrock provider via LiteLLM | P0 |
| FR14 | Enforce structured LLM outputs using Pydantic models (blocking mode) | P0 |

### Lifecycle & Observability

| ID | Requirement | Priority |
|----|-------------|----------|
| FR15 | Provide granular lifecycle hooks: `on_step_start`, `on_step_end`, `on_llm_start`, `on_llm_end` | P0 |
| FR16 | Execute `onFinish` callback with complete workflow result | P0 |
| FR17 | Execute `onError` callback with error context and step information | P0 |
| FR18 | Generate OpenTelemetry spans for all workflow and step executions | P0 |

### Streaming

| ID | Requirement | Priority |
|----|-------------|----------|
| FR19 | Support SSE streaming for real-time LLM responses (via optional framework extras) | P0 |

## Non-Functional Requirements

### Performance

| ID | Requirement | Metric |
|----|-------------|--------|
| NFR1 | Latency overhead per workflow step (excluding LLM time) | < 5ms |
| NFR2 | Support concurrent workflow executions | Non-blocking |

### Quality

| ID | Requirement | Metric |
|----|-------------|--------|
| NFR3 | Test coverage for domain logic | > 80% |
| NFR4 | Public API documentation | 100% docstrings |

### Compatibility

| ID | Requirement | Metric |
|----|-------------|--------|
| NFR5 | Execute existing beddel-ts YAML agents without modification | 100% |
| NFR6 | Python version support | 3.11+ (3.12 recommended) |

### Security

| ID | Requirement | Notes |
|----|-------------|-------|
| NFR7 | YAML parsing security | Only `yaml.safe_load()` |
| NFR8 | Secrets management | Environment variables only |
| NFR9 | Input validation | Guardrail-based, pre-LLM |
| NFR10 | Output validation | Schema enforcement |

### Maintainability

| ID | Requirement | Notes |
|----|-------------|-------|
| NFR11 | Architecture pattern | Hexagonal (Ports & Adapters) |
| NFR12 | Code style enforcement | Ruff 0.8+ |

### Multi-SDK Synchronization

| ID | Requirement | Notes |
|----|-------------|-------|
| NFR13 | Spec-driven development | JSON Schema in `spec/` directory |
| NFR14 | Shared test fixtures | YAML fixtures in `spec/fixtures/` |
| NFR15 | Cross-SDK validation | Fixture runner validates all SDKs |
| NFR16 | Version alignment | SemVer synchronized across SDKs |

### Observability

| ID | Requirement | Notes |
|----|-------------|-------|
| NFR17 | Tracing standard | OpenTelemetry native |
| NFR18 | Token/cost tracking | Per-step attribution |
| NFR19 | LangSmith compatibility | Optional OTLP export |
