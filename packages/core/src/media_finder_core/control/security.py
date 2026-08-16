"""Portable cursor, failure, and worker-boundary control primitives."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping

from media_finder_control import ControlFailure

__all__ = ["ControlPortError", "CursorCodec", "control_failure", "invoke"]


class ControlPortError(Exception):
    """Stable safe failure raised by a narrow outer adapter."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


class CursorCodec:
    """Domain-separated signed continuation cursors owned by core control."""

    def __init__(self, *, secret: bytes) -> None:
        self._secret = secret

    def encode(
        self,
        *,
        resource: str,
        filters: Mapping[str, object],
        position: tuple[str, ...],
    ) -> str:
        payload = json.dumps(
            {
                "api": "control-v1",
                "filters": filters,
                "position": position,
                "resource": resource,
                "version": 1,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._secret, b"cursor-v1\0" + payload, hashlib.sha256).digest()
        return f"{_urlsafe_encode(payload)}.{_urlsafe_encode(signature)}"

    def decode(
        self,
        token: str,
        *,
        resource: str,
        filters: Mapping[str, object],
    ) -> tuple[str, ...]:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = _urlsafe_decode(encoded_payload)
            signature = _urlsafe_decode(encoded_signature)
            expected = hmac.new(self._secret, b"cursor-v1\0" + payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            decoded = json.loads(payload)
            if (
                decoded.get("api") != "control-v1"
                or decoded.get("version") != 1
                or decoded.get("resource") != resource
                or decoded.get("filters") != filters
                or not isinstance(decoded.get("position"), list)
                or not all(isinstance(value, str) for value in decoded["position"])
            ):
                raise ValueError("binding")
            return tuple(decoded["position"])
        except Exception:
            raise ControlFailure(code="cursor_invalid", status=422) from None


def control_failure(error: Exception, fallback: str) -> ControlFailure:
    """Translate an internal failure without reflecting unsafe exception details."""

    if isinstance(error, ControlFailure):
        return error
    code = getattr(error, "code", fallback)
    if not isinstance(code, str) or not code:
        code = fallback
    if code.endswith("_not_found"):
        status = 404
    elif code.endswith("_conflict") or code == "confirmation_required":
        status = 409
    elif "unavailable" in code or "not_configured" in code or "missing" in code:
        status = 503
    else:
        status = 422
    return ControlFailure(code=code, status=status)


async def invoke[T](operation: Callable[[], T], *, fallback: str) -> T:
    """Run synchronous core orchestration in a worker and translate failures."""

    try:
        return await asyncio.to_thread(operation)
    except Exception as error:
        raise control_failure(error, fallback) from None
