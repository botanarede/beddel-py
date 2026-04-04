"""Multi-agent coordination strategy implementations.

Provides pluggable coordination patterns for orchestrating work across
multiple :class:`~beddel.domain.ports.IAgentAdapter` instances:

- :class:`SupervisorStrategy` — central agent decomposes, delegates, and
  synthesizes results from specialist agents.
"""

from beddel.domain.strategies.coordination.supervisor import SupervisorStrategy

__all__ = [
    "SupervisorStrategy",
]
