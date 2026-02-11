# Beddel

<!-- Badges (update URLs once repo and PyPI are live)
[![CI](https://github.com/OWNER/beddel/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/beddel/actions)
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

Requires Python 3.11+.

## Quickstart

```yaml
# workflow.yaml
name: summarize
description: Summarize a topic in one paragraph

steps:
  - id: generate
    primitive: llm
    config:
      # Model names may need updating as providers evolve.
      # Use stable names only — never experimental (-exp) suffixes.
      model: gemini/gemini-2.0-flash
      temperature: 0.7
    input:
      prompt: "Summarize the following topic in one paragraph: $input.topic"
```

```python
import asyncio
from beddel import Engine

async def main():
    engine = Engine.from_yaml("workflow.yaml")
    result = await engine.execute({"topic": "declarative AI workflows"})
    print(result.steps["generate"].output)

asyncio.run(main())
```

## Development Setup

Clone the repo and install dev dependencies from the SDK directory:

```bash
git clone https://github.com/OWNER/beddel.git
cd beddel/src/beddel-py
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

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
