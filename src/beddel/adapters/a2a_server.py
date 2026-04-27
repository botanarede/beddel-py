"""A2A protocol server adapter for Beddel workflows.

Exposes Beddel workflows as A2A-compliant agents with Agent Card discovery
and task lifecycle management via the a2a-sdk.

Public API:
    - :class:`BeddelA2AExecutor` — maps Beddel workflow execution to A2A
      task lifecycle events.
    - :func:`build_agent_card` — generates an A2A Agent Card from
      discovered workflows.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    DataPart,
    Message,
    Part,
    Role,
    TaskState,
    TextPart,
)

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import BeddelEvent, EventType, Workflow

logger = logging.getLogger(__name__)

__all__ = [
    "BeddelA2AExecutor",
    "build_agent_card",
]


def _agent_message(text: str) -> Message:
    """Create an A2A :class:`Message` with a single :class:`TextPart`."""
    return Message(
        role=Role.agent,
        parts=[Part(root=TextPart(text=text))],
        message_id=str(uuid.uuid4()),
    )


# Type alias for the workflow registry used by the executor.
# Maps workflow_id → (Workflow definition, WorkflowExecutor instance).
WorkflowRegistry = dict[str, tuple[Workflow, WorkflowExecutor]]


def _extract_workflow_params(
    context: RequestContext,
) -> tuple[str | None, dict[str, Any] | None]:
    """Extract ``workflow_id`` and ``inputs`` from A2A message parts.

    Scans the message's :class:`DataPart` entries for keys ``workflow_id``
    and ``inputs``.  Both may live in the same ``DataPart`` or in separate
    ones.

    The A2A SDK wraps concrete part types in a :class:`Part` discriminated
    union.  We unwrap via ``part.root`` to access the underlying
    :class:`DataPart`.

    Returns:
        A ``(workflow_id, inputs)`` tuple.  Either value may be ``None``
        when the corresponding key is absent from all parts.
    """
    workflow_id: str | None = None
    inputs: dict[str, Any] | None = None

    if context.message is None:
        return workflow_id, inputs

    for part in context.message.parts:
        # Unwrap the Part discriminated union to get the concrete type.
        inner = part.root if hasattr(part, "root") else part
        if not isinstance(inner, DataPart):
            continue
        data = inner.data
        if "workflow_id" in data and workflow_id is None:
            workflow_id = str(data["workflow_id"])
        if "inputs" in data and inputs is None:
            raw = data["inputs"]
            inputs = dict(raw) if isinstance(raw, dict) else None

    return workflow_id, inputs


class BeddelA2AExecutor(AgentExecutor):
    """Executes Beddel workflows via the A2A task lifecycle.

    The executor bridges the Beddel streaming execution model to the A2A
    protocol by consuming :class:`~beddel.domain.models.BeddelEvent`
    instances from :meth:`WorkflowExecutor.execute_stream` and translating
    them into :class:`TaskUpdater` calls that drive A2A task state
    transitions.

    Args:
        registry: Mapping of workflow IDs to ``(Workflow, WorkflowExecutor)``
            tuples.  Typically built by the CLI ``connect`` command from
            discovered workflow files.
    """

    def __init__(self, registry: WorkflowRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute a Beddel workflow mapped to an A2A task.

        Extracts ``workflow_id`` and ``inputs`` from the incoming A2A
        message, looks up the workflow in the registry, streams execution
        events, and maps each :class:`BeddelEvent` to the appropriate
        :class:`TaskUpdater` method.
        """
        task_id = context.task_id or ""
        context_id = context.context_id or ""
        updater = TaskUpdater(event_queue, task_id, context_id)

        workflow_id, inputs = _extract_workflow_params(context)

        if workflow_id is None:
            await updater.failed(
                message=_agent_message("Missing 'workflow_id' in message DataPart."),
            )
            return

        entry = self._registry.get(workflow_id)
        if entry is None:
            await updater.failed(
                message=_agent_message(f"Workflow '{workflow_id}' not found in registry."),
            )
            return

        workflow, executor = entry

        try:
            async for event in executor.execute_stream(workflow, inputs):
                await self._handle_event(updater, event)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Workflow %s failed unexpectedly", workflow_id)
            await updater.failed(message=_agent_message(str(exc)))

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel a running A2A task.

        Creates a :class:`TaskUpdater` and transitions the task to the
        cancelled state.
        """
        task_id = context.task_id or ""
        context_id = context.context_id or ""
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.cancel()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _handle_event(updater: TaskUpdater, event: BeddelEvent) -> None:
        """Map a single :class:`BeddelEvent` to a :class:`TaskUpdater` call."""
        et = event.event_type

        if et == EventType.WORKFLOW_START:
            await updater.start_work()

        elif et == EventType.STEP_START:
            step_name = event.step_id or "unknown"
            await updater.update_status(
                TaskState.working,
                message=_agent_message(f"Running step: {step_name}"),
            )

        elif et == EventType.TEXT_CHUNK:
            chunk = str(event.data.get("chunk", ""))
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=chunk))],
                append=True,
            )

        elif et == EventType.STEP_END:
            result_data = event.data.get("result", "")
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=str(result_data)))],
                name=event.step_id,
            )

        elif et == EventType.WORKFLOW_END:
            await updater.complete()

        elif et == EventType.ERROR:
            error_msg = str(event.data.get("error", "Unknown error"))
            await updater.failed(message=_agent_message(error_msg))


def build_agent_card(
    workflows: dict[str, tuple[Workflow, Any]],
    host: str = "127.0.0.1",
    port: int = 8000,
) -> AgentCard:
    """Build an A2A Agent Card from discovered workflows.

    Each workflow in the registry is mapped to an :class:`AgentSkill` with
    its ``id``, ``name``, ``description``, and ``tags`` derived from the
    workflow definition.

    Args:
        workflows: Mapping of workflow IDs to ``(Workflow, executor)``
            tuples.  Only the :class:`Workflow` is used; the executor
            value is ignored.
        host: Hostname for the agent URL.
        port: Port for the agent URL.

    Returns:
        A fully populated :class:`AgentCard` ready to be served at
        ``/.well-known/agent.json``.
    """
    skills: list[AgentSkill] = []

    for wf_id, (workflow, _executor) in workflows.items():
        tags = ["workflow"]
        if workflow.steps:
            tags.append(workflow.steps[0].primitive)

        skills.append(
            AgentSkill(
                id=wf_id,
                name=workflow.name,
                description=workflow.description or f"Execute workflow: {workflow.name}",
                tags=tags,
            ),
        )

    return AgentCard(
        name="Beddel Agent",
        description="A2A-compliant agent powered by Beddel workflows.",
        url=f"http://{host}:{port}",
        version="1.0.0",
        skills=skills,
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
    )
