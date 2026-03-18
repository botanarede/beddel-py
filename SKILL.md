---
name: beddel
description: Declarative YAML-based AI workflow engine — create, validate, and run AI workflows from the command line
version: 0.1.0
metadata:
  openclaw:
    requires:
      bins: ["python3", "pip"]
      env: []
    primaryEnv: ""
    install: "pip install beddel[cli]"
---

# Beddel — AI Workflow Engine CLI

Use this skill when the user wants to:
- Create or define AI workflows in YAML
- Validate workflow YAML files for correctness
- Execute AI workflows with custom inputs
- List available workflow primitives
- Start a workflow server for dashboard integration

## Installation

```bash
pip install beddel[cli]
```

## Commands

### Validate a workflow

Check if a YAML workflow file is valid:

```bash
beddel validate workflow.yaml
```

Output on success:
```
OK: workflow-id
  name: Workflow Name
  steps: 3
  primitives: llm, chat, output-generator
```

### Run a workflow

Execute a workflow with inputs:

```bash
beddel run workflow.yaml --input topic=astronomy --input language=english
```

For JSON output (machine-readable):

```bash
beddel run workflow.yaml --input topic=astronomy --json-output
```

### List primitives

Show all available built-in primitives:

```bash
beddel list-primitives
```

Available primitives: llm, chat, output-generator, call-agent, guardrail, tool, agent-exec

### Start the server

Serve workflows as HTTP/SSE endpoints for dashboard integration:

```bash
beddel serve --workflow workflow.yaml --port 8000
```

Serve multiple workflows:

```bash
beddel serve -w workflow1.yaml -w workflow2.yaml --port 8000
```

Endpoints:
- `POST /workflows/{id}` — Execute workflow (SSE response)
- `GET /health` — Health check

### Version

```bash
beddel version
```

## Workflow YAML Format

A minimal workflow file:

```yaml
id: hello-world
name: Hello World
description: A simple greeting workflow

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
      prompt: "Say hello and share a fun fact about $input.topic"
      temperature: 0.7
```

## Variable Resolution

Workflows support variable references:
- `$input.field` — Runtime inputs
- `$stepResult.step_id.field` — Previous step outputs
- `$env.VAR_NAME` — Environment variables

## Error Handling

Steps support error strategies: fail (default), skip, retry, fallback, delegate.

```yaml
steps:
  - id: risky-step
    primitive: llm
    config:
      model: gemini/gemini-2.0-flash
      prompt: "Generate content"
    execution_strategy:
      type: retry
      retry:
        max_attempts: 3
        backoff_base: 2.0
```

## Example Usage

User: "Create a workflow that summarizes a topic"
Agent: [Creates YAML file, validates with `beddel validate`, runs with `beddel run`]

User: "Start the beddel server with my workflows"
Agent: [Runs `beddel serve -w workflow1.yaml -w workflow2.yaml`]

User: "What primitives does beddel support?"
Agent: [Runs `beddel list-primitives`]
