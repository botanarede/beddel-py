"""ADK Event → BeddelEvent translation layer.

Converts raw ADK event dicts (Content/Parts model from Vertex AI Agent
Engine) into :class:`~beddel.domain.models.BeddelEvent` instances.

This is the **first stage** of a two-stage pipeline::

    ADK Event (Content/Parts dict)
        ↓ map_adk_events()  [THIS MODULE]
    BeddelEvent (domain model)
        ↓ BeddelAGUIAdapter.stream_events()  [existing]
    AG-UI BaseEvent (protocol)

The mapper emits synthetic ``WORKFLOW_START`` / ``WORKFLOW_END`` events to
bookend the stream, and translates each ADK part type to the corresponding
domain event:

- ``functionCall``     → ``STEP_START``
- ``functionResponse`` → ``STEP_END``
- ``text`` (non-empty) → ``TEXT_CHUNK``

Example::

    from beddel_ag_ui.adk_mapper import map_adk_events
    from beddel_ag_ui.adapter import BeddelAGUIAdapter

    async for agui_event in BeddelAGUIAdapter.stream_events(
        map_adk_events(adk_event_stream),
    ):
        yield agui_event.model_dump_json()
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.models import BeddelEvent, EventType

__all__ = ["map_adk_events"]

logger = logging.getLogger(__name__)


async def map_adk_events(
    events: AsyncGenerator[dict[str, Any], None],
) -> AsyncGenerator[BeddelEvent, None]:
    """Convert ADK event dicts to BeddelEvent instances.

    Iterates over raw ADK event dictionaries (as returned by Agent Engine
    ``:streamQuery``), extracts ``content.parts``, and yields the
    corresponding :class:`BeddelEvent` for each recognised part type.

    A synthetic ``WORKFLOW_START`` is emitted before the first event and
    ``WORKFLOW_END`` after the last.

    Args:
        events: Async generator yielding ADK event dicts with the
            ``content.parts`` structure.

    Yields:
        :class:`BeddelEvent` instances suitable for piping into
        :meth:`BeddelAGUIAdapter.stream_events`.
    """
    yield BeddelEvent(event_type=EventType.WORKFLOW_START)

    async for event in events:
        content = event.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                yield BeddelEvent(
                    event_type=EventType.STEP_START,
                    step_id=fc.get("name", "unknown"),
                    data={"args": fc.get("args", {})},
                )
            elif "functionResponse" in part:
                fr = part["functionResponse"]
                yield BeddelEvent(
                    event_type=EventType.STEP_END,
                    step_id=fr.get("name", "unknown"),
                    data={"response": fr.get("response", {})},
                )
            elif "text" in part:
                text = part["text"]
                if text:  # Skip empty text
                    yield BeddelEvent(
                        event_type=EventType.TEXT_CHUNK,
                        data={"text": text},
                    )

    yield BeddelEvent(event_type=EventType.WORKFLOW_END)
