"""Dashboard Agent Pipeline — real-time agent execution event translation.

Provides :class:`AgentPipelineAdapter` for translating domain
:class:`~beddel.domain.models.AgentResult` events into Pipeline Protocol
SSE events, and :class:`AgentPipelineEvent` / :class:`AgentHealthStatus`
data models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter

    from beddel.integrations.dashboard.pipeline.router import RegisterAdapterFn

__all__ = [
    "AgentHealthStatus",
    "AgentPipelineAdapter",
    "AgentPipelineEvent",
    "ClaudePipelineAdapter",
    "CodexPipelineAdapter",
    "OpenClawPipelineAdapter",
    "create_agent_pipeline_router",
]


def create_agent_pipeline_router() -> tuple[APIRouter, RegisterAdapterFn]:
    """Create a FastAPI router for agent pipeline endpoints.

    Returns:
        A 2-tuple of ``(APIRouter, register_adapter)`` callable.
    """
    from beddel.integrations.dashboard.pipeline.router import (
        create_agent_pipeline_router as _create_router,
    )

    return _create_router()


def __getattr__(name: str) -> object:
    """Lazy-load pipeline symbols to avoid import-time side effects."""
    if name == "AgentPipelineAdapter":
        from beddel.integrations.dashboard.pipeline.agent_adapter import (
            AgentPipelineAdapter,
        )

        return AgentPipelineAdapter
    if name in ("AgentPipelineEvent", "AgentHealthStatus"):
        from beddel.integrations.dashboard.pipeline import models

        return getattr(models, name)
    if name == "OpenClawPipelineAdapter":
        from beddel.integrations.dashboard.pipeline.openclaw_pipeline import (
            OpenClawPipelineAdapter,
        )

        return OpenClawPipelineAdapter
    if name == "ClaudePipelineAdapter":
        from beddel.integrations.dashboard.pipeline.claude_pipeline import (
            ClaudePipelineAdapter,
        )

        return ClaudePipelineAdapter
    if name == "CodexPipelineAdapter":
        from beddel.integrations.dashboard.pipeline.codex_pipeline import (
            CodexPipelineAdapter,
        )

        return CodexPipelineAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
