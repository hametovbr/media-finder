"""Generate the deterministic processor API version-one schema artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from media_finder_core.platform import create_database, session_factory
from media_finder_server.processor_api import create_processor_app

DEFAULT_OUTPUT = Path("schemas/processor-api/v1/openapi.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    engine = create_database("sqlite://")
    try:
        app = create_processor_app(
            integration_token="schema-generation-token",
            database_engine=engine,
            sessions=session_factory(engine),
        )
        content = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    finally:
        engine.dispose()

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
