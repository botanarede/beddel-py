#!/usr/bin/env python3
"""Runner for the Imagen generation workflow.

Registers the imagen_generate tool and executes the workflow.

Usage:
    python examples/run_imagen.py \\
        --prompt "A serene yoga scene with tropical leaves" \\
        --aspect-ratio "16:9" \\
        --output "/tmp/hero.webp"

    # Or with all defaults:
    python examples/run_imagen.py --prompt "Zen garden at sunrise"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path for local dev
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from examples.tools.imagen_tool import imagen_generate


async def main(prompt: str, aspect_ratio: str, output_path: str) -> None:
    # 1. Parse workflow
    workflow_path = Path(__file__).parent / "imagen-generate.yaml"
    workflow = WorkflowParser.parse_file(str(workflow_path))

    # 2. Create registry with imagen tool
    registry = PrimitiveRegistry()

    # 3. Create executor
    executor = WorkflowExecutor(registry)

    # 4. Register the imagen_generate tool
    executor.tool_registry["imagen_generate"] = imagen_generate

    # 5. Run
    inputs = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "output_path": output_path,
        "project": "beddel-beta",
        "location": "us-central1",
    }

    print("Running Imagen workflow...")
    print(f"  Prompt: {prompt}")
    print(f"  Aspect: {aspect_ratio}")
    print(f"  Output: {output_path}")
    print()

    result = await executor.execute(workflow, inputs)

    print(f"\nWorkflow status: {result.status}")
    if result.output:
        print(result.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate images with Imagen 4 Ultra")
    parser.add_argument("--prompt", required=True, help="Image description")
    parser.add_argument("--aspect-ratio", default="16:9", help="Aspect ratio (default: 16:9)")
    parser.add_argument("--output", default="/tmp/imagen_output.webp", help="Output path")
    args = parser.parse_args()

    asyncio.run(main(args.prompt, args.aspect_ratio, args.output))
