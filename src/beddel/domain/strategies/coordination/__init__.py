"""Multi-agent coordination strategy implementations.

Provides pluggable coordination patterns for orchestrating work across
multiple :class:`~beddel.domain.ports.IAgentAdapter` instances:

- :class:`SupervisorStrategy` — central agent decomposes, delegates, and
  synthesizes results from specialist agents.
- :class:`HandoffStrategy` — agent-to-agent transfer with context passing,
  inspired by the OpenAI Agents SDK handoff primitive.
"""

from beddel.domain.strategies.coordination.handoff import HandoffStrategy
from beddel.domain.strategies.coordination.supervisor import SupervisorStrategy

__all__ = [
    "HandoffStrategy",
    "SupervisorStrategy",
]
