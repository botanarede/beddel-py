"""Agent pipeline router — placeholder for Task 3."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter

__all__ = ["create_agent_pipeline_router"]


def create_agent_pipeline_router() -> APIRouter:
    """Create a FastAPI router for agent pipeline endpoints.

    Returns:
        A FastAPI APIRouter with agent pipeline endpoints.

    Raises:
        NotImplementedError: Until Task 3 implements the full router.
    """
    raise NotImplementedError("Agent pipeline router not yet implemented (Task 3)")
