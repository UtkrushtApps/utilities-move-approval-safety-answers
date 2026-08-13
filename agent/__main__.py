from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv

from agent.config import Settings
from agent.fixture_loader import validate_fixture_bundle
from agent.model_client import RealModelClient


def selfcheck() -> int:
    load_dotenv(".env")
    settings = Settings.from_environment()
    record_count = validate_fixture_bundle(settings.fixture_path)
    print(f"Validated {record_count} incident fixture records")

    if os.getenv("OPENAI_API_KEY"):
        client = RealModelClient(settings)
        asyncio.run(client.ping())
        print("Provider ping completed")
    else:
        print("OPENAI_API_KEY is not set; skipping optional provider ping")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selfcheck", action="store_true")
    arguments = parser.parse_args()
    if arguments.selfcheck:
        return selfcheck()
    parser.error("Use --selfcheck for scaffold readiness")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
