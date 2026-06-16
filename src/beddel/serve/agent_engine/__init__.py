"""Agent Engine sub-module of the serve tier.

Contains ports, models, and route registration for
the Agent Engine sidebar integration.
"""

from .adapter import VertexAgentEngineAdapter
from .models import AgentInfo, ChatChunk
from .ports import IAgentRuntimeAdapter
from .routes import register_agent_engine_routes

__all__ = [
    "IAgentRuntimeAdapter",
    "AgentInfo",
    "ChatChunk",
    "VertexAgentEngineAdapter",
    "register_agent_engine_routes",
]
