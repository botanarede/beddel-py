# Beddel

<!-- Badges (update URLs once CI is live)
[![CI](https://github.com/botanarede/beddel-py/actions/workflows/ci.yml/badge.svg)](https://github.com/botanarede/beddel-py/actions)
[![PyPI version](https://img.shields.io/pypi/v/beddel.svg)](https://pypi.org/project/beddel/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
-->

Declarative YAML-based AI workflow engine for Python.

Define outcome-driven AI workflows in YAML — the engine handles execution with conditional branching, retry strategies, multi-provider LLM abstraction, and compositional primitives. YAML for the backbone, code escape hatches for complex logic.

## Installation

```bash
pip install beddel
```

With FastAPI integration:

```bash
pip install beddel[fastapi]
```

> **Planned:** A `beddel[lite]` extra for minimal installs (without optional integrations) is planned for a future release.

Requires Python 3.11+.

## Quickstart

Get a workflow running in under 15 minutes.

### 1. Install

```bash
pip install beddel
```

### 2. Set your API key

Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey), then export it:

```bash
export GEMINI_API_KEY="your-key-here"
```

### 3. Create a workflow

Save this as `workflow.yaml`:

```yaml
id: hello-world
name: Hello World
description: A minimal workflow that greets the user with a fun fact about a topic.

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
      # Model names may need updating as providers release new versions.
      model: gemini/gemini-2.0-flash
      prompt: "Say hello and share one fun fact about $input.topic"
      temperature: 0.7
```

### 4. Create a runner script

Save this as `run_workflow.py`:

```python
import asyncio
from pathlib import Path

from beddel.adapters.litellm_adapter import LiteLLMAdapter
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins

async def main():
    # Parse the workflow YAML
    yaml_str = Path("workflow.yaml").read_text()
    workflow = WorkflowParser.parse(yaml_str)

    # Build the primitive registry
    registry = PrimitiveRegistry()
    register_builtins(registry)

    # Create the LLM adapter (reads GEMINI_API_KEY from env)
    adapter = LiteLLMAdapter()

    # Wire up and execute
    executor = WorkflowExecutor(registry, provider=adapter)
    result = await executor.execute(workflow, inputs={"topic": "astronomy"})

    # Print the response
    print(result["step_results"]["greet"]["content"])

asyncio.run(main())
```

### 5. Run it

```bash
python run_workflow.py
```

The model responds with a friendly greeting and a fun fact about astronomy. The exact output varies per run since `temperature` is set above zero.

> **Note:** Model names use the stable [LiteLLM](https://docs.litellm.ai/) format (`provider/model`). Avoid experimental (`-exp`) suffixes. Update the model name if a version becomes unavailable.

## Variable Resolution

Beddel workflows use `$input.<field>` placeholders in YAML templates to inject values at runtime. When you call `executor.execute(workflow, inputs={"topic": "astronomy"})`, the engine resolves every `$input.<field>` reference before the step executes.

```yaml
steps:
  - id: greet
    primitive: llm
    config:
      prompt: "Tell me about $input.topic"
```

In this example, `$input.topic` resolves to `"astronomy"` at execution time. Other namespaces are also available: `$stepResult.*` references outputs from previously executed steps, and `$env.*` reads environment variables.

## Development Setup

Clone the repo and install dev dependencies from the SDK directory:

```bash
git clone https://github.com/botanarede/beddel-py.git
cd beddel/src/beddel-py
pip install -e ".[dev]"
```

Run tests:

```bash
python -Wd -m pytest
```

The `-Wd` flag turns `DeprecationWarning` into errors, catching deprecated API usage early. This is the recommended way to run tests during development. Plain `pytest` still works if you don't need deprecation checks.

Lint and format:

```bash
ruff check .
ruff format .
```

Type check:

```bash
mypy src/
```

## Contributing

Contributions are welcome. Guidelines and a contributor workflow will be documented here as the project matures. For now, open an issue to discuss before submitting a PR.

## License

MIT
