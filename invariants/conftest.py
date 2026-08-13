from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from agent.config import BASE_DIR
from agent.fixture_loader import load_incident_fixtures
from agent.orchestrator import MoveAgent
from agent.schemas import MoveDecision
from agent.state import MoveStore
from agent.tools import CloseServiceTool


class FixtureModelBoundary:
    def __init__(self, decisions: list[MoveDecision]) -> None:
        self._decisions = deque(decisions)

    async def decide(self, message: str) -> MoveDecision:
        del message
        return self._decisions.popleft()


@pytest.fixture
def incident_cases():
    return load_incident_fixtures(BASE_DIR / "fixtures" / "incident_cases.json")


@pytest.fixture
def store(tmp_path: Path) -> MoveStore:
    return MoveStore(tmp_path / "test-moves.db")


def build_agent(store: MoveStore, decisions: list[MoveDecision]) -> MoveAgent:
    boundary = FixtureModelBoundary(decisions)
    return MoveAgent(boundary, store, CloseServiceTool(store))
