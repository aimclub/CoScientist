"""A2A host/port/URL maps, derived from the agent declarations in system.yaml.

Each agent with an ``a2a`` section gets an entry keyed by its ``a2a.key``. The
default port comes from the YAML and can be overridden per agent with the
``<KEY>_PORT`` env var (e.g. ``RESEARCH_PORT``).

``A2A_HOST`` is the default internal host used by RemoteA2aAgent to reach peer
agents. Override a single peer with ``<KEY>_HOST`` (e.g. ``RESEARCH_HOST``) when
agents run in separate containers. ``A2A_PUBLIC_HOST`` is the advertised host
placed into AgentCards for clients outside that internal network. When omitted,
it falls back to ``A2A_HOST``.
"""
import os

from CoScientist.assembly.schema import get_config

A2A_HOST = os.getenv("A2A_HOST", "localhost")
A2A_PUBLIC_HOST = os.getenv("A2A_PUBLIC_HOST", A2A_HOST)


def _agent_ports() -> dict[str, int]:
    return {
        agent.a2a.key: int(os.getenv(f"{agent.a2a.key.upper()}_PORT", str(agent.a2a.port)))
        for agent in get_config().a2a_agents()
    }


AGENT_PORTS: dict[str, int] = _agent_ports()


def _agent_host(key: str) -> str:
    return os.getenv(f"{key.upper()}_HOST", A2A_HOST)


AGENT_URLS: dict[str, str] = {
    name: f"http://{A2A_PUBLIC_HOST}:{port}/"
    for name, port in AGENT_PORTS.items()
}

# A2A well-known agent card URLs used by RemoteA2aAgent
AGENT_CARD_URLS: dict[str, str] = {
    name: f"http://{_agent_host(name)}:{port}/.well-known/agent.json"
    for name, port in AGENT_PORTS.items()
}
