"""Machine-readable, value-free module manifests."""

from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import Field, HttpUrl, field_validator, model_validator

from .common import PublicModel

SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SEMVER = re.compile(SEMVER_PATTERN)
_TRANSLATION_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class ModuleKind(StrEnum):
    METADATA_PROVIDER = "metadata-provider"
    RELEASE_PROVIDER = "release-provider"
    DOWNLOAD_CLIENT = "download-client"


class EnvironmentVariableSpec(PublicModel):
    """Value-free declaration of one exact process variable."""

    name: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    required: bool
    secret: bool
    description_key: str

    @field_validator("description_key")
    @classmethod
    def validate_description_key(cls, value: str) -> str:
        if _TRANSLATION_KEY.fullmatch(value) is None:
            raise ValueError("environment_description_key_invalid")
        return value


class AttributionSpec(PublicModel):
    notice_key: str
    url: HttpUrl | None = None

    @field_validator("notice_key")
    @classmethod
    def validate_notice_key(cls, value: str) -> str:
        if _TRANSLATION_KEY.fullmatch(value) is None:
            raise ValueError("attribution_notice_key_invalid")
        return value


class ModuleManifest(PublicModel):
    """Canonical static contract read from a module's ``module.toml``."""

    module_id: Annotated[
        str,
        Field(max_length=100, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"),
    ]
    module_kind: ModuleKind
    module_version: str
    sdk_compatibility: str
    contract_version: Annotated[str, Field(min_length=1, max_length=32)]
    name_key: str
    capabilities: frozenset[str]
    translation_keys: frozenset[str]
    environment: tuple[EnvironmentVariableSpec, ...] = ()
    attribution: AttributionSpec | None = None

    @field_validator("module_version")
    @classmethod
    def validate_module_version(cls, value: str) -> str:
        if _SEMVER.fullmatch(value) is None:
            raise ValueError("module_version_invalid")
        return value

    @field_validator("sdk_compatibility")
    @classmethod
    def validate_sdk_compatibility(cls, value: str) -> str:
        try:
            if not value.strip():
                raise InvalidSpecifier(value)
            SpecifierSet(value)
        except InvalidSpecifier as error:
            raise ValueError("module_sdk_range_invalid") from error
        return value

    @field_validator("name_key")
    @classmethod
    def validate_name_key(cls, value: str) -> str:
        if _TRANSLATION_KEY.fullmatch(value) is None:
            raise ValueError("module_name_key_invalid")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capability_names(cls, value: frozenset[str]) -> frozenset[str]:
        if not value or any(
            re.fullmatch(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", item) is None for item in value
        ):
            raise ValueError("module_capability_name_invalid")
        return value

    @field_validator("translation_keys")
    @classmethod
    def validate_translation_keys(cls, value: frozenset[str]) -> frozenset[str]:
        if not value or any(_TRANSLATION_KEY.fullmatch(item) is None for item in value):
            raise ValueError("module_translation_key_invalid")
        return value

    @model_validator(mode="after")
    def validate_manifest_relationships(self) -> ModuleManifest:
        names = tuple(item.name for item in self.environment)
        if len(names) != len(set(names)):
            raise ValueError("environment_variable_duplicate")
        required_keys = {self.name_key}
        required_keys.update(item.description_key for item in self.environment)
        if self.attribution is not None:
            required_keys.add(self.attribution.notice_key)
        if not required_keys.issubset(self.translation_keys):
            raise ValueError("translation_key_undeclared")
        return self

    def sdk_range(self) -> SpecifierSet:
        """Return the validated compatibility range."""

        return SpecifierSet(self.sdk_compatibility)


def parse_manifest(content: bytes) -> ModuleManifest:
    """Parse one UTF-8 TOML manifest without executable module imports."""

    return ModuleManifest.model_validate(tomllib.loads(content.decode("utf-8")))


def load_manifest(path: str | Path) -> ModuleManifest:
    """Load one manifest from an explicit package or wheel-extraction path."""

    return parse_manifest(Path(path).read_bytes())


__all__ = [
    "SEMVER_PATTERN",
    "AttributionSpec",
    "EnvironmentVariableSpec",
    "ModuleKind",
    "ModuleManifest",
    "load_manifest",
    "parse_manifest",
]
