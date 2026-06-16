"""Beddel serve tier — delivery layer for runtime adapters.

This tier sits outside the domain core and depends inward only (serve → domain).
"""

from .agent_engine import AgentInfo, ChatChunk, IAgentRuntimeAdapter, VertexAgentEngineAdapter

__all__ = ["IAgentRuntimeAdapter", "AgentInfo", "ChatChunk", "VertexAgentEngineAdapter"]
