# Goals and Background Context

## Goals

**MVP Goals:**

- Execute 100% of existing beddel-ts YAML workflows without modifications
- Provide core primitives (`llm`, `chat`, `output-generator`, `call-agent`) with support for 3 providers (OpenRouter, Google, Bedrock)
- Achieve time-to-first-workflow < 15 minutes for new users
- Maintain latency overhead < 5ms per workflow step
- Reach 80%+ test coverage for domain logic

**Strategic Goals:**

- Serve as the canonical Single Source of Truth for AI-assisted translation to all languages and technologies
- Implement all 8 Agent-Native features identified in the Handbook (phased rollout)
- Build active community with 500+ monthly PyPI downloads

## Background Context

The Python AI agent ecosystem lacks a declarative solution that unifies workflow orchestration, multi-provider LLM support, and agent-native patterns. Developers currently combine LangChain for chains, OpenAI SDK for calls, and ad-hoc code for patterns like reflection and approval—resulting in fragmented, hard-to-maintain codebases.

The **beddel-ts** (TypeScript) validated the YAML-first approach with positive early adoption, but its architecture doesn't address the 8 critical features from the Agent-Native Handbook. Beddel Python represents a redesign that implements these patterns natively, not as extensions.

**Key Strategic Decisions:**

1. **Repository Structure:** Monorepo (`botanarede/beddel`) with `spec/` and `src/beddel-{lang}/` directories
2. **LLM SDK Strategy:** LiteLLM as Python foundation (100+ providers); spec defines interface for other languages
3. **Multi-Language Support:** Python is source of truth; AI-assisted translation to all languages/technologies uses spec + Python as inputs
4. **Phased Repository Strategy:** Monorepo initially → separate repos when independent release cycles are needed

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-02-03 | 0.1 | Initial PRD draft with refined goals and strategic decisions | John (PM) |
