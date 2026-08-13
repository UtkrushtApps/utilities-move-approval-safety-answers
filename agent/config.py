from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path("/root/task")


@dataclass(frozen=True)
class Settings:
    model_name: str
    api_key: str | None
    base_url: str | None
    database_path: Path
    fixture_path: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY") or None,
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            database_path=Path(
                os.getenv("MOVE_DATABASE_PATH", str(BASE_DIR / "move-agent.db"))
            ),
            fixture_path=BASE_DIR / "fixtures" / "incident_cases.json",
        )
