from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from agent.schemas import IncidentFixture

_FIXTURE_ADAPTER = TypeAdapter(list[IncidentFixture])


def load_incident_fixtures(path: Path) -> list[IncidentFixture]:
    with path.open("r", encoding="utf-8") as fixture_file:
        payload = json.load(fixture_file)
    return _FIXTURE_ADAPTER.validate_python(payload)


def validate_fixture_bundle(path: Path) -> int:
    fixtures = load_incident_fixtures(path)
    if not fixtures:
        raise ValueError("Incident fixture bundle is empty")
    request_ids = {item.request.request_id for item in fixtures}
    if len(request_ids) != len(fixtures):
        raise ValueError("Incident fixture request identifiers must be unique")
    return len(fixtures)
