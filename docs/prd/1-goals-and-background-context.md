# 1. Goals and Background Context

## 1.1 Goals

- Deliver a production-ready Python SDK that enables declarative YAML-based AI workflows with adaptive execution, reducing development time by 60%+ vs imperative code
- Achieve < 15 minutes from `pip install` to first working workflow execution
- Provide compositional primitives (llm, chat, output-generator, call-agent, guardrail, tool) that cover 95% of production AI workflow patterns
- Establish multi-provider LLM abstraction with tier selection, eliminating provider lock-in
- Deliver production-grade observability (OpenTelemetry tracing, lifecycle hooks) and framework integration (FastAPI, SSE) out of the box
- Maintain > 80% domain test coverage with spec-driven fixtures as the single source of truth
- Enable post-MVP adaptive execution patterns (reflection loops, goal-oriented execution, parallel fan-out) and enterprise safety features (HITL, PII tokenization, state persistence)

## 1.2 Background Context

The AI agent ecosystem lacks a declarative workflow engine that treats agent-native patterns — reflection loops, human-in-the-loop, conditional branching, multi-provider routing — as first-class compositional primitives. Developers currently wire together 5-10 libraries with hundreds of lines of imperative Python for every project, with no standard patterns for production concerns like retry, observability, or guardrails.

PayPal's research (arXiv 2512.19769) demonstrated that declarative YAML DSLs reduce development time by 60% and deploy 3x faster than imperative code at production scale. Beddel applies this insight as a Python SDK using Hexagonal Architecture: YAML for the workflow backbone, code escape hatches for complex logic, and a port/adapter pattern that keeps the domain core free of external dependencies. Three independent research studies identified if/then/else branching, HITL, reflection loops, and goal-oriented execution as consensus patterns — all mapped to Beddel's epic roadmap.

## 1.3 Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| February 2026 | v4 | Initial PRD generated from project brief | John (PM) |

---
