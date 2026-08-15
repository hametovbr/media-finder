"""Static first-party module registration and typed configuration normalization."""

from typing import Any

from pydantic import BaseModel, ValidationError

from .qbittorrent import QbittorrentConfig

DOWNLOAD_CLIENT_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "qbittorrent": QbittorrentConfig,
}


def normalize_download_client_config(module_key: str, payload: dict[str, object]) -> dict[str, Any]:
    model = DOWNLOAD_CLIENT_CONFIG_MODELS.get(module_key)
    if model is None:
        raise ValueError("download_client_module_unknown")
    try:
        validated = model.model_validate(payload)
    except ValidationError:
        raise ValueError("download_client_configuration_invalid") from None
    return validated.model_dump(mode="json")
