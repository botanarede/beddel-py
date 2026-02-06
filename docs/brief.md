# Project Brief: Beddel Python

> **Version:** 1.2.0  
> **Date:** February 4, 2026  
> **Status:** Approved  
> **Synchronized with:** PRD v0.4

---

## Executive Summary

**Beddel Python** is the canonical Python implementation of the Beddel Protocol—an Agent-Native Workflow Engine that enables declarative AI pipelines through YAML definitions. It serves as the Single Source of Truth for multi-language SDK translation (Python → all languages/technologies via AI).

**Primary Problem:** Current AI workflow tools lack built-in support for agent-native patterns like reflection loops, approval mechanisms, state persistence, and tier selection.

**Target Market:** Python developers building AI agents using LangChain, OpenAI SDK, Google GenAI, and similar frameworks.

**Key Value Proposition:** A declarative YAML-based workflow engine with atomic primitives that agents compose into goal-oriented loops—enabling production-ready AI pipelines without boilerplate code.

---

## Problem Statement

### Current State & Pain Points

1. **Fragmented Tooling:** Developers manually integrate multiple libraries for agent-native behaviors
2. **Code-Heavy Pipelines:** Building AI workflows requires extensive Python code
3. **Missing Agent Patterns:** beddel-ts lacks critical features from Agent-Native Handbook
4. **Provider Lock-in:** Switching LLM providers requires significant code changes

### Why Existing Solutions Fall Short

| Solution | Gap |
|----------|-----|
| LangChain | Complex; doesn't enforce agent-native patterns declaratively |
| AutoGen | Multi-agent conversation focus, not workflow orchestration |
| Native SDKs | Require significant boilerplate for production features |

---

## Proposed Solution

A **Hexagonal Architecture** Python package that:

1. Parses YAML workflows using `yaml.safe_load()` with Pydantic validation
2. Resolves variables with `$input.*`, `$stepResult.*`, `$env.*` patterns
3. Executes steps asynchronously with early-return for streaming
4. Provides extensible registries for primitives, providers, and callbacks

**Core Concept:** Tools are atomic primitives; features are outcomes. Beddel provides the primitives—you compose them into workflows.

**Key Differentiators:**
- Declarative YAML definitions
- Built-in Agent-Native features (phased rollout)
- Multi-provider support via LiteLLM (100+ providers)
- SSE streaming for real-time responses

---

## Target Users

### Primary: Python AI Developers

- **Profile:** Backend developers (2-5 years), familiar with async Python
- **Current Workflow:** Building agents with OpenAI/LangChain, managing complex prompt chains
- **Pain Points:** Boilerplate code, lack of observability, difficulty with multi-step workflows
- **Goals:** Ship production-ready AI features faster

### Secondary: AI/ML Teams

- **Profile:** ML engineers integrating LLMs into Python systems
- **Pain Points:** Translation from prototype to production, monitoring LLM calls
- **Goals:** Standardized patterns for AI pipeline deployment

---

## Goals & Success Metrics

### Business Objectives

- **Package Adoption:** 500+ PyPI downloads in first month
- **TypeScript Parity:** 100% YAML agent compatibility with beddel-ts
- **Feature Completeness:** All 8 Agent-Native features (phased)

### User Success Metrics

- Time to first workflow: < 15 minutes
- LoC reduction vs raw SDK: 70%+
- Workflow success rate: > 95%

### Key Performance Indicators

| KPI | Target |
|-----|--------|
| Test Coverage | > 80% domain logic |
| Latency Overhead | < 5ms per step |
| API Documentation | 100% docstrings |

---

## MVP Scope

### Core Features (Must Have)

- **YAML Parser:** Secure loading with Pydantic validation (FR1)
- **Variable Resolver:** Recursive `$input`, `$stepResult`, `$env` patterns (FR2)
- **Workflow Executor:** Async sequential execution with early-return (FR3)
- **Return Template:** Optional explicit API response contract (FR4.1)
- **Primitive Registry:** Decorator-based extensibility (FR4)
- **6 Base Primitives:** `llm`, `chat`, `output-generator`, `call-agent`, `guardrail`, `tool` (FR5-FR10)
- **Provider Support:** OpenRouter, Google Gemini, AWS Bedrock via LiteLLM (FR11-FR14)
- **Lifecycle Hooks:** `on_step_start`, `on_step_end`, `onFinish`, `onError` (FR15-FR17)
- **OpenTelemetry:** Span generation for observability (FR18)
- **SSE Streaming:** FastAPI integration (FR19)

### Out of Scope for MVP

- Web UI / dashboard
- Database adapters (beyond file-based)
- Multi-tenancy / API key management
- Auto-scaling / distributed execution
- CI/CD pipelines (Post-MVP E10)

### MVP Success Criteria

1. Execute all YAML agents from beddel-ts without modification
2. Pass 80%+ test coverage for domain logic
3. FastAPI integration demo with SSE streaming

---

## Post-MVP Vision

### Phase 2 Features (E6-E9)

| Epic | Description |
|------|-------------|
| E6 | Advanced Tool Primitive: Full MCP integration, external tool servers |
| E7 | Memory & State: session persistence, checkpoints |
| E8 | Agent-Native P1: Tier selection, approval mechanism |
| E9 | Agent-Native P2: Reflection loops, skill composition |

### Phase 3 (E10-E12)

| Epic | Description |
|------|-------------|
| E10 | DevOps & CI/CD: Pipeline setup, automated testing |
| E11 | Integration Primitives: Notion, Google Business, service-specific |
| E12 | TypeScript SDK: AI-assisted translation from Python |

### Long-term Vision (6-12 months)

- Multi-language SDKs (all languages/technologies) using Python as source
- Enterprise features: audit logging, role-based access
- Marketplace for shareable skills and agent templates
- VS Code extension for YAML authoring

---

## Technical Considerations

### Platform Requirements

| Requirement | Specification |
|-------------|---------------|
| Python | 3.11+ required, 3.12 recommended |
| Framework | FastAPI 0.115+ |
| Async Runtime | `asyncio` with `async/await` |

### Core Dependencies

| Package | Purpose |
|---------|---------|
| `pydantic` 2.x | Schema validation, structured outputs |
| `litellm` | Multi-provider LLM abstraction |
| `pyyaml` 6.x | YAML parsing (safe_load) |
| `opentelemetry-api` 1.x | Observability |
| `httpx` 0.27+ | Async HTTP |

### Architecture

- **Pattern:** Hexagonal (Ports & Adapters)
- **Structure:** `src/beddel-py/src/beddel/domain/`, `adapters/`, `primitives/`
- **Repository:** Monorepo (`botanarede/beddel`) with `spec/` and `src/beddel-{lang}/`
- **Security:** `yaml.safe_load()` only, env-based secrets

---

## Constraints & Assumptions

### Constraints

| Area | Detail |
|------|--------|
| Budget | Solo developer / small team |
| Timeline | MVP in 4-6 weeks (5 Epics) |
| Compatibility | 100% YAML parity with beddel-ts |
| Security | No `yaml.load()`, env-only secrets |

### Key Assumptions

- Python 3.11+ adoption is sufficient for target audience
- LiteLLM maintains backward compatibility
- Developers prefer YAML over Python for simple workflows
- FastAPI + SSE covers all streaming use cases

---

## Risks & Open Questions

### Key Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| TypeScript parity gaps | High | Integration tests with shared YAML fixtures |
| LiteLLM API changes | Medium | Version pinning, adapter pattern |
| Timeline slip | Medium | Stories not yet drafted; create immediately |

### Open Questions

1. Should skills be loaded lazily or eagerly at startup?
2. Best approach for PII tokenization—regex or NER models?
3. How should approval mechanism integrate with external services?

---

## Related Documents

- [PRD](docs/prd.md) - Detailed requirements (v0.4)
- [Architecture](docs/architecture.md) - Technical design (v1.0.0)
- [AGENTS.md](AGENTS.md) - AI agent guidelines

---

## Next Steps

1. **PO:** Shard PRD into epics → `@po *shard-doc`
2. **SM:** Draft Epic 1 stories → `@sm *draft`
3. **Dev:** Begin implementation after story approval

---

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2026-02-04 | 1.1.0 | Created brief synchronized with PRD v0.3 | BMad Master |
| 2026-02-04 | 1.2.0 | Synchronized with PRD v0.4: repository strategy, return template, expanded post-MVP | Sarah (PO) |
