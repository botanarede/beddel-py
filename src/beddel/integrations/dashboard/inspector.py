"""Workflow metadata inspector for Dashboard Server Protocol endpoints.

Provides :class:`WorkflowInspector`, a read-only wrapper around a dict of
:class:`~beddel.domain.models.Workflow` objects that exposes summary and
detail views consumed by the dashboard API.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.models import Workflow

__all__ = ["WorkflowInspector"]


class WorkflowInspector:
    """Read-only inspector that exposes workflow metadata for the dashboard.

    Holds a mapping of ``{workflow_id: Workflow}`` and provides two views:

    * :meth:`list_workflows` — lightweight summaries for the list endpoint.
    * :meth:`get_workflow_detail` — full serialized workflow for the detail
      endpoint.

    Args:
        workflows: Mapping of workflow IDs to :class:`Workflow` instances.

    Example::

        inspector = WorkflowInspector({"wf-1": my_workflow})
        summaries = inspector.list_workflows()
        detail = inspector.get_workflow_detail("wf-1")
    """

    def __init__(self, workflows: dict[str, Workflow]) -> None:
        self._workflows = workflows

    def list_workflows(self) -> list[dict[str, Any]]:
        """Return lightweight summaries of all registered workflows.

        Each summary dict contains:

        - ``id``: Workflow identifier.
        - ``name``: Human-readable name.
        - ``description``: Workflow description.
        - ``version``: Semantic version string.
        - ``step_count``: Number of top-level steps.

        Returns:
            List of summary dicts, one per workflow.
        """
        return [
            {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "version": wf.version,
                "step_count": len(wf.steps),
                "status": "published",
                "category": "automation",
                "author": "local",
                "tags": [],
                "created_at": "1970-01-01T00:00:00Z",
                "updated_at": "1970-01-01T00:00:00Z",
            }
            for wf in self._workflows.values()
        ]

    def get_workflow_detail(self, workflow_id: str) -> dict[str, Any] | None:
        """Return full serialized detail for a single workflow.

        Uses Pydantic's ``model_dump(by_alias=True)`` to preserve field
        aliases (e.g. ``if`` instead of ``if_condition``).

        Args:
            workflow_id: The workflow identifier to look up.

        Returns:
            Full workflow dict including steps, input_schema, and metadata,
            or ``None`` if the workflow is not found.
        """
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return None
        return wf.model_dump(by_alias=True)
