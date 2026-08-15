"""Data-only descriptions used by core to render generic settings controls."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, SecretStr


@dataclass(frozen=True, slots=True)
class SettingsField:
    name: str
    title_key: str
    required: bool
    secret: bool
    order: int
    input_type: str
    html: None = None
    javascript: None = None


def describe_settings(config_model: type[BaseModel]) -> list[SettingsField]:
    fields: list[SettingsField] = []
    for name, definition in config_model.model_fields.items():
        extra = (
            definition.json_schema_extra if isinstance(definition.json_schema_extra, dict) else {}
        )
        annotation: Any = definition.annotation
        raw_order = extra.get("order", 100)
        order = raw_order if isinstance(raw_order, int) else 100
        fields.append(
            SettingsField(
                name=name,
                title_key=definition.title or f"settings.{name}",
                required=definition.is_required(),
                secret=bool(extra.get("secret")) or annotation is SecretStr,
                order=order,
                input_type="password"
                if bool(extra.get("secret")) or annotation is SecretStr
                else "text",
            )
        )
    return sorted(fields, key=lambda item: (item.order, item.name))
