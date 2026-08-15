"""Bounded URL-encoded form parsing for the bundled UI."""

from urllib.parse import parse_qs

from fastapi import Request

MAX_FORM_BYTES = 1024 * 1024


class FormBodyTooLarge(ValueError):
    pass


async def decode_form(request: Request) -> dict[str, str]:
    cached = getattr(request.state, "media_finder_decoded_form", None)
    if isinstance(cached, dict):
        return dict(cached)
    declared = request.headers.get("content-length")
    try:
        if declared is not None and int(declared) > MAX_FORM_BYTES:
            raise FormBodyTooLarge("ui_form_too_large")
    except ValueError:
        raise FormBodyTooLarge("ui_form_too_large") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FORM_BYTES:
            raise FormBodyTooLarge("ui_form_too_large")
    try:
        values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}
    decoded = {key: items[-1] for key, items in values.items() if items}
    request.state.media_finder_decoded_form = decoded
    return dict(decoded)
