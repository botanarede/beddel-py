#!/usr/bin/env python3
"""ADK Agent with Beddel Workflow Tools — Bridge Pattern Example.

Demonstrates how to use ``bridge-adk-kit`` to expose Beddel YAML workflows
as ADK tools, then create an ADK agent that can invoke them.

Prerequisites::

    pip install beddel[bridge-adk]

The bridge pattern lets ADK handle agent orchestration while Beddel handles
declarative workflow definition.  ``BeddelADKTool`` wraps a workflow YAML as
an ADK ``FunctionTool`` — the ADK agent sees it as a regular tool and can
invoke it with structured inputs.

Usage::

    python examples/adk_agent_with_beddel.py

Note: This example uses inline YAML strings for simplicity.  In production,
workflows would be loaded from files on disk.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from beddel_bridge_adk import BeddelADKTool, create_adk_agent

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# 1. Define two simple workflow YAMLs (inline for this example)
# ---------------------------------------------------------------------------

SUMMARIZE_WORKFLOW = """\
id: summarize
description: Summarize the given text into a concise paragraph.
steps:
  - id: summarize_step
    primitive: llm
    config:
      model: gemini-2.0-flash
      messages:
        - role: system
          content: You are a concise summarizer.
        - role: user
          content: "Summarize this: $input.text"
"""

TRANSLATE_WORKFLOW = """\
id: translate
description: Translate text from one language to another.
steps:
  - id: translate_step
    primitive: llm
    config:
      model: gemini-2.0-flash
      messages:
        - role: system
          content: "You are a translator. Translate to $input.target_language."
        - role: user
          content: "$input.text"
"""


async def main() -> None:
    """Create an ADK agent with two Beddel workflow tools and show setup."""
    # Write inline YAMLs to temp files (BeddelADKTool reads from file paths)
    with tempfile.TemporaryDirectory() as tmpdir:
        summarize_path = Path(tmpdir) / "summarize.yaml"
        translate_path = Path(tmpdir) / "translate.yaml"
        summarize_path.write_text(SUMMARIZE_WORKFLOW)
        translate_path.write_text(TRANSLATE_WORKFLOW)

        # 2. Create a WorkflowExecutor with a basic registry
        registry = PrimitiveRegistry()
        executor = WorkflowExecutor(registry)

        # 3. Wrap each workflow as a BeddelADKTool
        summarize_tool = BeddelADKTool(
            workflow_path=str(summarize_path),
            executor=executor,
            name="summarize",
            description="Summarize text into a concise paragraph.",
        )

        translate_tool = BeddelADKTool(
            workflow_path=str(translate_path),
            executor=executor,
            name="translate",
            description="Translate text from one language to another.",
        )

        # 4. Create an ADK agent with both tools
        agent = create_adk_agent(
            name="research_assistant",
            model="gemini-2.0-flash",
            tools=[summarize_tool, translate_tool],
            instruction=(
                "You are a research assistant. Use the summarize tool to "
                "condense long texts and the translate tool to convert text "
                "between languages."
            ),
        )

        print(f"ADK Agent created: {agent.name}")
        print(f"  Model: {agent.model}")
        print(f"  Tools: {[t.name for t in [summarize_tool, translate_tool]]}")
        print()
        print("The agent is ready to be used with ADK's Runner:")
        print()
        print("  from google.adk.runners import Runner")
        print("  from google.adk.sessions import InMemorySessionService")
        print()
        print("  runner = Runner(agent=agent, app_name='demo',")
        print("                  session_service=InMemorySessionService())")
        print("  # ... send messages via runner.run_async()")


if __name__ == "__main__":
    asyncio.run(main())
