import hashlib
import json
from pathlib import Path

from fake_control_gateway import FakeControlGateway
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity

SNAPSHOT = Path("docs/api/control-v1.openapi.json")
GENERATED_TYPES = Path("packages/builtin-ui/web/src/api/control.generated.ts")


def _canonical_schema() -> str:
    app = create_control_app(
        gateway=FakeControlGateway(),
        security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
    )
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def test_control_openapi_is_deterministic_safe_and_current() -> None:
    assert SNAPSHOT.read_text(encoding="utf-8") == _canonical_schema()
    schema = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert set(schema["paths"]) == {
        "/v1/about",
        "/v1/acquisitions",
        "/v1/acquisitions/{acquisition_id}/reconcile",
        "/v1/collections",
        "/v1/collections/{collection_id}",
        "/v1/download-destinations",
        "/v1/integrations",
        "/v1/manual-imports",
        "/v1/manual-imports/{token}/confirm",
        "/v1/media-items",
        "/v1/media-items/{item_id}",
        "/v1/media-items/{item_id}/episode-imports",
        "/v1/media-items/{item_id}/manual-metadata",
        "/v1/media-items/{item_id}/release-searches",
        "/v1/metadata-providers",
        "/v1/metadata-searches",
        "/v1/metadata-selections/{token}",
        "/v1/session",
    }
    serialized = json.dumps(schema).casefold()
    assert "controlerrorenvelope" in serialized
    assert "raw_payload" not in serialized
    assert "bearer" not in serialized
    assert not any("export" in path or "nfo" in path for path in schema["paths"])


def test_builtin_ui_control_types_follow_the_checked_openapi() -> None:
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()

    assert GENERATED_TYPES.is_file(), "generate the built-in UI control types"
    assert GENERATED_TYPES.read_text(encoding="utf-8").startswith(f"// OpenAPI SHA256: {digest}\n")
