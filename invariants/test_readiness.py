from __future__ import annotations

from agent.config import BASE_DIR
from agent.fixture_loader import validate_fixture_bundle


def test_incident_fixture_bundle_is_valid():
    count = validate_fixture_bundle(BASE_DIR / "fixtures" / "incident_cases.json")

    assert count > 1
