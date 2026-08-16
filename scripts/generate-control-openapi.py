"""Generate the deterministic browser control API schema snapshot."""

import json
from pathlib import Path

from media_finder_builtin_ui.fake import FakeControlGateway
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity


def main() -> None:
    app = create_control_app(
        gateway=FakeControlGateway(),
        security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
    )
    output = Path("docs/api/control-v1.openapi.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
