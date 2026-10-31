from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.migration.e2e.harness import Agent

AgentFactory = Callable[..., Agent]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def start_agent(tmp_path: Path) -> Iterator[AgentFactory]:
    """start_agent("A", profile="default", **env) -> a live agent subprocess, killed at teardown."""
    agents: list[Agent] = []

    def factory(name: str, profile: str, **env: str) -> Agent:
        base = {"COUNTER_STEP_S": "0.1", "COUNTER_TARGET": "100000"}
        agent = Agent(name, free_port(), tmp_path / name, profile, {**base, **env})
        agents.append(agent)
        return agent

    yield factory
    for agent in agents:
        agent.close()


@pytest.fixture
def dev_two(start_agent: AgentFactory) -> tuple[Agent, Agent]:
    """The `npm run dev:two` pair: A on the default profile, B on arm64-lowspec."""
    return start_agent("Device A", "default"), start_agent("Device B", "arm64-lowspec")
