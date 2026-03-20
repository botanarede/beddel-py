# Beddel

[![CI](https://github.com/botanarede/beddel-py/actions/workflows/ci.yml/badge.svg)](https://github.com/botanarede/beddel-py/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy.readthedocs.io/)
[![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://docs.pydantic.dev/)
[![Hatch](https://img.shields.io/badge/%F0%9F%A5%9A-Hatch-4051b5.svg)](https://github.com/pypa/hatch)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

<!-- Uncomment when published to PyPI:
[![PyPI version](https://img.shields.io/pypi/v/beddel.svg)](https://pypi.org/project/beddel/)
[![PyPI downloads](https://img.shields.io/pypi/dm/beddel.svg)](https://pypi.org/project/beddel/)
-->

Declarative YAML-based AI workflow engine for Python.

Define outcome-driven AI workflows in YAML — the engine handles adaptive execution with conditional branching, retry strategies, multi-provider LLM abstraction, and compositional primitives. YAML for the backbone, code escape hatches for complex logic.

```yaml
steps:
  - id: greet
    primitive: llm
    config:
      model: gemini/gemini-2.0-flash
      prompt: "Say hello and share a fun fact about $input.topic"
      temperature: 0.7
```

## Why Beddel

- Write workflows in YAML, not hundreds of lines of Python
- 7 built-in primitives cover most AI workflow patterns out of the box
- Multi-provider LLM support via [LiteLLM](https://docs.litellm.ai/) (100+ providers)
- Adaptive execution: branching, retry with backoff, fallback, skip, delegate
- OpenTelemetry tracing with token usage tracking per step
- Lifecycle hooks for custom logging, metrics, and side effects
- Expose workflows as HTTP/SSE endpoints with one function call
- Hexagonal architecture — swap adapters without touching domain logic

## Installation

```bash
# Core only (parser, resolver, executor — no external adapters)
pip install beddel

# With LLM adapters (LiteLLM, OpenTelemetry, httpx)
pip install beddel[adapters]

# With FastAPI integration (HTTP endpoints + SSE streaming)
pip install beddel[fastapi]

# With CLI (validate, run, serve workflows)
pip install beddel[cli]

# Everything
pip install beddel[all]
```

Requires Python 3.11+.

## Quickstart

Get a workflow running in under 5 minutes.

### 1. Install

```bash
pip install beddel[adapters]
```

### 2. Set your API key

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey):

```bash
export GEMINI_API_KEY="your-key-here"
```

### 3. Create a workflow

Save as `workflow.yaml`:

```yaml
id: hello-world
name: Hello World
description: A minimal workflow that greets the user with a fun fact.

input_schema:
  type: object
  properties:
    topic:
      type: string
  required:
    - topic

steps:
  - id: greet
    primitive: llm
    config:
      model: gemini/gemini-2.0-flash
      prompt: "Say hello and share one fun fact about $input.topic"
      temperature: 0.7
```

### 4. Run it

```python
import asyncio
from pathlib import Path

from beddel.adapters.litellm_adapter import LiteLLMAdapter
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins

async def main():
    workflow = WorkflowParser.parse(Path("workflow.yaml").read_text())

    registry = PrimitiveRegistry()
    register_builtins(registry)

    executor = WorkflowExecutor(registry, provider=LiteLLMAdapter())
    result = await executor.execute(workflow, inputs={"topic": "astronomy"})

    print(result["step_results"]["greet"]["content"])

asyncio.run(main())
```

```bash
python run_workflow.py
```

> Model names use the [LiteLLM format](https://docs.litellm.ai/) (`provider/model`). Avoid experimental (`-exp`) suffixes — they get retired without notice.


## Features

### Adaptive Core Engine (Epic 1)

The foundation. Parses YAML workflows, resolves variables, and executes steps with adaptive control flow.

**YAML Parser** — Secure loading via `yaml.safe_load()` with Pydantic 2.x validation. Supports workflow metadata, step definitions, variable references, conditional expressions, and execution strategy declarations.

**Variable Resolver** — Extensible namespace system with three built-in namespaces and a registration mechanism for custom ones:

```yaml
prompt: "Tell me about $input.topic"           # Runtime inputs
prompt: "Expand on $stepResult.step1.content"   # Previous step outputs
prompt: "Using key $env.API_KEY"                # Environment variables
```

```python
# Register custom namespaces
resolver.register_namespace("memory", my_memory_handler)
```

**Adaptive Workflow Executor** — Sequential execution with step-level conditional branching (`if/then/else`), configurable execution strategies per step, and step-level timeout support. The executor evaluates conditions and adapts flow — not a pure sequential dispatcher.

**Execution Strategies** — Five strategies per step, with exponential backoff and jitter for retries:

```yaml
steps:
  - id: risky-call
    primitive: llm
    config:
      model: gemini/gemini-2.0-flash
      prompt: "Generate content about $input.topic"
    execution_strategy:
      type: retry
      retry:
        max_attempts: 3
        backoff_base: 2.0
```

| Strategy | Behavior |
|----------|----------|
| `fail` | Stop workflow on error (default) |
| `skip` | Log error, continue to next step |
| `retry` | Retry with exponential backoff and jitter |
| `fallback` | Execute an alternative step on failure |
| `delegate` | Delegate error recovery to agent judgment |

**Primitive Registry** — Instance-based registration with contract validation:

```python
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry

registry = PrimitiveRegistry()

class MyPrimitive(IPrimitive):
    async def execute(self, config, context):
        return {"result": "custom logic here"}

registry.register("my-custom-primitive", MyPrimitive())
```

Or use the `@primitive` decorator for module-level registration:

```python
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import primitive

@primitive("my-custom-primitive")
class MyPrimitive(IPrimitive):
    async def execute(self, config, context):
        return {"result": "custom logic here"}
```

**LiteLLM Adapter** — Multi-provider LLM abstraction supporting OpenRouter, Google Gemini, AWS Bedrock, Anthropic, and all [LiteLLM-supported providers](https://docs.litellm.ai/docs/providers). Explicit API key resolution from environment variables for resilience against upstream library changes.

### Compositional Primitives (Epic 2)

Seven built-in primitives that compose into complex agent behaviors.

| Primitive | Description |
|-----------|-------------|
| `llm` | Single-turn LLM invocation with streaming support |
| `chat` | Multi-turn conversation with message history and context windowing |
| `output-generator` | Template-based output rendering (JSON, Markdown, text) |
| `guardrail` | Input/output validation with 4 failure strategies |
| `call-agent` | Nested workflow invocation with depth tracking |
| `tool` | External function invocation (sync and async) |
| `agent-exec` | Unified agent adapter for external agent delegation |

**chat** — Multi-turn conversations with automatic context windowing:

```yaml
steps:
  - id: conversation
    primitive: chat
    config:
      model: gemini/gemini-2.0-flash
      system: "You are a helpful coding assistant."
      messages:
        - role: user
          content: "What is Python?"
        - role: assistant
          content: "$stepResult.prev.content"
        - role: user
          content: "Tell me more about async/await"
      max_messages: 50
      max_context_tokens: 4000
```

**guardrail** — Validate LLM outputs with four failure strategies:

```yaml
steps:
  - id: validate
    primitive: guardrail
    config:
      data: "$stepResult.generate.content"
      schema:
        fields:
          name: { type: str }
          age: { type: int }
      strategy: correct  # raise | return_errors | correct | delegate
```

| Strategy | Behavior | LLM Required |
|----------|----------|:------------:|
| `raise` | Hard fail with validation errors | No |
| `return_errors` | Soft fail — returns errors alongside data | No |
| `correct` | JSON repair (parse → strip markdown fences → retry) | No |
| `delegate` | Ask LLM to fix validation errors, retry up to N times | Yes |

**call-agent** — Compose workflows by nesting them:

```yaml
steps:
  - id: delegate
    primitive: call-agent
    config:
      workflow: summarizer-workflow
      inputs:
        text: "$stepResult.extract.content"
      max_depth: 5
```

**tool** — Invoke registered functions (sync or async):

```yaml
steps:
  - id: search
    primitive: tool
    config:
      tool: web_search
      arguments:
        query: "$input.question"
```

```python
# Register tools before execution
tool_registry = {
    "web_search": my_search_function,
    "calculate": my_calc_function,
}
```

### Observability & Integration (Epic 3)

Production-grade observability and framework integration.

**OpenTelemetry Tracing** — Opt-in tracing with three nesting levels and token usage tracking:

```python
from beddel.adapters.otel_adapter import OpenTelemetryAdapter

tracer = OpenTelemetryAdapter(service_name="my-app")
executor = WorkflowExecutor(registry, provider=adapter, tracer=tracer)
```

Spans generated:
- `beddel.workflow` — workflow-level span with `beddel.workflow_id`
- `beddel.step.{step_id}` — step-level span with token usage (`gen_ai.usage.*`)
- `beddel.primitive.{name}` — primitive-level span with model and provider attributes

Zero overhead when tracing is disabled (all calls gated behind `if tracer is not None`).

**Lifecycle Hooks** — Granular event system for custom logging, metrics, or side effects:

```python
from beddel.domain.ports import ILifecycleHook

class MyHook(ILifecycleHook):
    async def on_workflow_start(self, workflow_id, inputs):
        print(f"Starting {workflow_id}")

    async def on_step_end(self, step_id, primitive, result):
        print(f"Step {step_id} completed")

    async def on_error(self, step_id, error):
        print(f"Error in {step_id}: {error}")

executor = WorkflowExecutor(registry, provider=adapter, hooks=[MyHook()])
```

Events: `on_workflow_start`, `on_workflow_end`, `on_step_start`, `on_step_end`, `on_error`, `on_retry`. Hook failures are silently caught — a misbehaving hook never breaks workflow execution.

**FastAPI Integration** — Expose workflows as HTTP/SSE endpoints with one function call:

```python
from fastapi import FastAPI
from beddel.integrations.fastapi import create_beddel_handler

app = FastAPI()
router = create_beddel_handler(workflow)  # auto-creates provider + registry
app.include_router(router)
```

The handler streams workflow execution via Server-Sent Events (W3C-compliant). Clients receive real-time events: `WORKFLOW_START`, `STEP_START`, `STEP_END`, `WORKFLOW_END`.

```bash
pip install beddel[fastapi]
beddel serve -w workflow.yaml --port 8000
```

Endpoints:
- `POST /workflows/{id}` — Execute workflow (SSE response)
- `GET /health` — Health check


## CLI

Beddel includes a command-line interface for validating, running, and serving workflows.

```bash
pip install beddel[cli]
```

### Validate a workflow

```bash
beddel validate workflow.yaml
```

Output:
```
OK: hello-world
  name: Hello World
  steps: 1
  primitives: llm
```

### Run a workflow

```bash
beddel run workflow.yaml --input topic=astronomy
```

Machine-readable output:

```bash
beddel run workflow.yaml --input topic=astronomy --json-output
```

### List primitives

```bash
beddel list-primitives
```

### Start the server

```bash
beddel serve -w workflow.yaml --port 8000
beddel serve -w flow1.yaml -w flow2.yaml --port 8000
```

### Version

```bash
beddel version
```

## OpenClaw Integration

Beddel works as an [OpenClaw](https://openclaw.com) agent skill. After installing with `pip install beddel[cli]`, the `beddel` command is available for any OpenClaw agent to create, validate, and execute AI workflows.

### Practical examples

**Agent that validates workflows before execution:**

An OpenClaw agent can validate YAML files authored by users or other agents, catching schema errors before runtime:

```bash
openclaw agent --message "Validate my workflow at ./flows/pipeline.yaml" \
  --agent main
```

The agent calls `beddel validate ./flows/pipeline.yaml` and reports any issues.

**Agent-driven workflow execution with dynamic inputs:**

An OpenClaw agent can run Beddel workflows as part of a larger task, passing context-dependent inputs:

```bash
openclaw agent --message "Run the summarizer workflow for the topic 'quantum computing'" \
  --agent main
```

The agent calls `beddel run summarizer.yaml --input topic="quantum computing"` and processes the result.

**Serving workflows for dashboard integration:**

An OpenClaw agent can start the Beddel server to expose workflows as HTTP endpoints, enabling integration with dashboards or other services:

```bash
openclaw agent --message "Start the beddel server with all workflows in ./flows/" \
  --agent main
```

The agent discovers YAML files and runs `beddel serve -w flow1.yaml -w flow2.yaml --port 8000`.

**Multi-agent pipeline with Beddel as the execution engine:**

In a multi-agent setup, one agent (e.g., an architect) designs the workflow YAML, another (e.g., a QA agent) validates it, and a third executes it:

```
Architect agent → writes workflow.yaml
QA agent        → beddel validate workflow.yaml
Executor agent  → beddel run workflow.yaml --input topic=security --json-output
```

See `SKILL.md` for the full skill manifest and OpenClaw metadata.

## Architecture

Beddel follows Hexagonal Architecture (Ports & Adapters). The domain core never imports from adapters or integrations — all external dependencies flow through port interfaces.

```
┌─────────────────────────────────────────────┐
│              Integrations                    │
│         FastAPI  ·  SSE Streaming            │
├─────────────────────────────────────────────┤
│               Adapters                       │
│    LiteLLM  ·  OpenTelemetry  ·  Hooks       │
├─────────────────────────────────────────────┤
│            Compositional Primitives          │
│  llm · chat · output · guardrail · tool · …  │
├─────────────────────────────────────────────┤
│              Domain Core                     │
│  Parser · Resolver · Executor · Registry     │
│  Models · Ports (interfaces)                 │
└─────────────────────────────────────────────┘
```

## Development Setup

```bash
git clone https://github.com/botanarede/beddel-py.git
cd beddel/src/beddel-py
pip install -e ".[dev]"
```

Run all quality gates (recommended):

```bash
bash scripts/run-gates.sh
```

Or individually:

```bash
# Tests
python -Wd -m pytest

# Lint + format
ruff check .
ruff format .

# Type check
mypy src/
```

The `-Wd` flag turns `DeprecationWarning` into errors, catching deprecated API usage early.

## Roadmap

Epics 1–3 (Adaptive Core, Compositional Primitives, Observability & Integration) are complete. Upcoming:

- **Epic 4** — Adaptive Execution Patterns: reflection loops, parallel execution, circuit breaker, goal-oriented execution, MCP-native tool integration
- **Epic 5** — Agent Autonomy & Safety: human-in-the-loop, model tier selection, PII tokenization, state persistence, cost controls

## Contributing

Contributions are welcome. Open an issue to discuss before submitting a PR. Guidelines will be documented as the project matures.

## Newsletter

[![Subscribe on Substack](https://img.shields.io/badge/Subscribe-Substack-orange?style=for-the-badge&logo=substack)](https://beddelprotocol.substack.com/subscribe)

## License

MIT
