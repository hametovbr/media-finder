import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from media_finder_core.platform import create_database, session_factory
from media_finder_server.processor_api import create_processor_app

SNAPSHOT = Path("schemas/processor-api/v1/openapi.json")


def _canonical_schema() -> str:
    engine = create_database("sqlite://")
    try:
        app = create_processor_app(
            integration_token="schema-generation-token",
            database_engine=engine,
            sessions=session_factory(engine),
        )
        return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    finally:
        engine.dispose()


def _operation(schema: dict[str, Any], path: str) -> dict[str, Any]:
    return schema["paths"][path]["get"]


def test_processor_openapi_is_current_and_semantically_complete() -> None:
    assert SNAPSHOT.read_text(encoding="utf-8") == _canonical_schema()
    schema = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    assert schema["info"] == {"title": "Media Finder processor API", "version": "1"}
    assert set(schema["paths"]) == {
        "/health/live",
        "/health/ready",
        "/api/v1/media-items/{item_id}/metadata",
        "/api/v1/acquisitions/{acquisition_id}/metadata",
        "/api/v1/media-items/{item_id}/exports/naming",
        "/api/v1/acquisitions/{acquisition_id}/exports/naming",
        "/api/v1/media-items/{item_id}/exports/nfo",
        "/api/v1/acquisitions/{acquisition_id}/exports/nfo",
    }

    assert "security" not in _operation(schema, "/health/live")
    assert "security" not in _operation(schema, "/health/ready")
    ready_responses = _operation(schema, "/health/ready")["responses"]
    assert ready_responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProcessorErrorEnvelope"
    }

    metadata_paths = (
        "/api/v1/media-items/{item_id}/metadata",
        "/api/v1/acquisitions/{acquisition_id}/metadata",
    )
    naming_paths = (
        "/api/v1/media-items/{item_id}/exports/naming",
        "/api/v1/acquisitions/{acquisition_id}/exports/naming",
    )
    nfo_paths = (
        "/api/v1/media-items/{item_id}/exports/nfo",
        "/api/v1/acquisitions/{acquisition_id}/exports/nfo",
    )

    for path in metadata_paths:
        operation = _operation(schema, path)
        assert operation["security"] == [{"HTTPBearer": []}]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/NormalizedMetadata"
        }

    provenance = schema["components"]["schemas"]["Provenance"]
    assert "provider_key" in provenance["properties"]
    assert "provider_id" not in provenance["properties"]

    for path in naming_paths:
        operation = _operation(schema, path)
        assert operation["security"] == [{"HTTPBearer": []}]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/NamingResult"
        }

    for path in nfo_paths:
        operation = _operation(schema, path)
        assert operation["security"] == [{"HTTPBearer": []}]
        successful = operation["responses"]["200"]
        assert set(successful["content"]) == {"application/xml"}
        assert successful["content"]["application/xml"]["schema"] == {"type": "string"}
        assert set(successful["headers"]) == {
            "Content-Disposition",
            "Sunset",
            "Warning",
            "X-Media-Finder-Metadata-Expires",
        }

    for path in (*metadata_paths, *naming_paths, *nfo_paths):
        responses = _operation(schema, path)["responses"]
        for status_code in ("401", "404", "410", "422", "500"):
            assert responses[status_code]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ProcessorErrorEnvelope"
            }

    serialized = json.dumps(schema).casefold()
    assert "raw_payload" not in serialized
    assert "effective_payload" not in serialized
    assert "controlerror" not in serialized


def test_processor_openapi_generator_is_byte_stable(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    command = [sys.executable, "scripts/generate-processor-openapi.py", "--output"]

    subprocess.run([*command, str(first)], check=True)
    subprocess.run([*command, str(second)], check=True)

    assert first.read_bytes() == second.read_bytes() == SNAPSHOT.read_bytes()
