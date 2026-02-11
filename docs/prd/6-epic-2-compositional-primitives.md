# 6. Epic 2: Compositional Primitives

**Goal:** Expand the primitive library with the full set of compositional building blocks, enabling developers to compose complex AI workflows from atomic, well-tested primitives.

## Story 2.1: Chat Primitive

As a developer,
I want a multi-turn conversation primitive,
so that my workflows can maintain conversational context across multiple LLM interactions.

**Acceptance Criteria:**
1. `chat` primitive manages message history with role-based messages (system, user, assistant)
2. Context windowing limits message history to configurable token/message count
3. Streaming support via async generators
4. Reads `context.metadata["llm_provider"]` for the LLM provider instance
5. Spec fixtures validate multi-turn conversation flows

## Story 2.2: Output Generator & Guardrail Primitives

As a developer,
I want to format workflow outputs with templates and validate inputs/outputs with guardrails,
so that my workflows produce consistent, safe results.

**Acceptance Criteria:**
1. `output-generator` primitive renders templates with variable interpolation via VariableResolver (documentation accurately describes this as variable interpolation, not Jinja2)
2. Supports structured output formatting (JSON, Markdown, custom templates)
3. `guardrail` primitive validates inputs/outputs with strategies: `raise`, `return_errors`, `correct`, `delegate`
4. Pydantic-based structured output enforcement with JSON repair/recovery for malformed LLM responses
5. Spec fixtures for each primitive and each guardrail failure strategy

## Story 2.3: Call-Agent & Tool Primitives

As a developer,
I want to invoke nested workflows and external tools from within my workflows,
so that I can compose complex agent behaviors from simple building blocks.

**Acceptance Criteria:**
1. `call-agent` primitive invokes nested workflows with configurable max depth and context passing
2. Result propagation from nested workflows back to the parent workflow
3. `tool` primitive invokes functions with schema discovery, input validation, and structured results
4. Both sync and async tools are supported
5. Both primitives read required dependencies from `ExecutionContext.metadata` per the Wiring Contract
6. Spec fixtures validate nested invocation and tool execution

---
