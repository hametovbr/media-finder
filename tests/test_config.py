import pytest

from media_finder.config import (
    EnvReference,
    SettingsRepository,
    redact,
    resolve_env_reference,
    safe_url_origin,
)


def test_only_valid_environment_references_are_persistable(monkeypatch) -> None:
    reference = EnvReference(value="env:MEDIA_FINDER_TOKEN")
    monkeypatch.setenv("MEDIA_FINDER_TOKEN", "top-secret")
    assert resolve_env_reference(reference).get_secret_value() == "top-secret"
    with pytest.raises(ValueError):
        EnvReference(value="top-secret")
    with pytest.raises(ValueError):
        EnvReference(value="env:path/to/value")


def test_redaction_removes_secrets_and_sensitive_urls() -> None:
    value = "failed https://user:pass@example.test/a?api_key=secret#fragment top-secret"
    result = redact(value, secrets=["top-secret", "secret"])
    assert "pass" not in result
    assert "secret" not in result
    assert "api_key" not in result
    assert result == "failed https://example.test [REDACTED]"


def test_redaction_drops_sensitive_url_paths_queries_and_fragments() -> None:
    result = redact(
        "upstream https://example.test/passkey/token/file?apikey=hidden#secret",
        secrets=["hidden"],
    )
    assert result == "upstream https://example.test"


def test_malformed_authority_is_omitted_without_leaking_secret() -> None:
    diagnostic = "failed https://example.test:TOKEN/private?api_key=SECRET#fragment"
    rendered = redact(diagnostic, secrets=["SECRET"])
    assert rendered == "failed [REDACTED]"
    assert safe_url_origin(diagnostic) is None
    assert "TOKEN" not in rendered


def test_settings_repository_persists_only_secret_reference(database) -> None:
    settings = SettingsRepository(database)
    settings.set_secret_reference("integration.token", "env:MEDIA_FINDER_TOKEN")
    assert settings.get_reference("integration.token") == EnvReference(
        value="env:MEDIA_FINDER_TOKEN"
    )
    with pytest.raises(ValueError):
        settings.set_secret_reference("integration.token", "resolved-secret")
