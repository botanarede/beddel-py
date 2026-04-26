"""Workflow listing endpoints — discovery API for the Live view.

Provides :func:`create_workflow_listing_router`, a factory that creates a
FastAPI :class:`~fastapi.APIRouter` with two ``GET`` endpoints:

- ``GET /`` — list all loaded workflows (summary: id, name, description,
  version, step_count).
- ``GET /{workflow_id}`` — full detail for a single workflow including
  ``yaml_content``, ``input_schema``, and ``steps``.

These endpoints are consumed by the Beddel Dashboard "Live" view to
discover and inspect available workflows before execution.

Example::

    from beddel_ag_ui.listing import create_workflow_listing_router

    workflows = {"my-wf": (workflow, yaml_path)}
    router = create_workflow_listing_router(workflows)
    app.include_router(router, prefix="/workflows")

Requires the ``default`` extra: ``pip install beddel[default]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from beddel.domain.models import Workflow

__all__ = ["create_workflow_listing_router"]


def create_workflow_listing_router(
    workflows: dict[str, tuple[Workflow, Path]],
) -> APIRouter:
    """Create a workflow listing router for workflow discovery.

    Accepts a map of ``workflow_id → (workflow, yaml_path)`` pairs and
    returns an :class:`~fastapi.APIRouter` with two endpoints:

    - ``GET /`` — returns a summary list of all loaded workflows.
    - ``GET /{workflow_id}`` — returns full detail for a single workflow,
      including the raw YAML content, input schema, and step list.
      Returns 404 if the workflow ID is not found.

    Args:
        workflows: Mapping of workflow IDs to ``(Workflow, Path)`` tuples.
            The :class:`~pathlib.Path` points to the YAML source file,
            used to serve ``yaml_content`` in the detail endpoint.

    Returns:
        A :class:`~fastapi.APIRouter` with ``GET /`` and
        ``GET /{workflow_id}`` endpoints for workflow discovery.

    Example::

        from fastapi import FastAPI
        from beddel_ag_ui.listing import create_workflow_listing_router

        workflows = {"demo": (workflow, Path("demo.yaml"))}
        app = FastAPI()
        router = create_workflow_listing_router(workflows)
        app.include_router(router, prefix="/workflows")
    """
    router = APIRouter()

    @router.get("/")
    async def _list_workflows() -> list[dict[str, Any]]:
        """Return summary list of all loaded workflows."""
        results: list[dict[str, Any]] = []
        for wf_id, (wf, _wf_path) in workflows.items():
            results.append(
                {
                    "id": wf_id,
                    "name": wf.name,
                    "description": wf.description or "",
                    "version": wf.version or "1.0",
                    "step_count": len(wf.steps),
                }
            )
        return results

    @router.get("/{workflow_id}", response_model=None)
    async def _get_workflow(workflow_id: str) -> dict[str, Any] | JSONResponse:
        """Return full detail for a single workflow, or 404 if not found."""
        entry = workflows.get(workflow_id)
        if entry is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        wf, wf_path = entry
        steps_list = [
            {
                "id": s.id,
                "name": s.id,
                "primitive": s.primitive,
            }
            for s in wf.steps
        ]
        return {
            "id": wf.id,
            "name": wf.name,
            "description": wf.description or "",
            "version": wf.version or "1.0",
            "step_count": len(wf.steps),
            "yaml_content": wf_path.read_text(),
            "input_schema": wf.input_schema if wf.input_schema else None,
            "steps": steps_list,
        }

    return router
