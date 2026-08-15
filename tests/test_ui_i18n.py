# ruff: noqa: RUF001
import pytest


@pytest.mark.parametrize(
    ("code", "english", "russian"),
    [
        ("csrf_invalid", "Request rejected.", "Запрос отклонён."),
        (
            "collection_name_required",
            "A collection name is required.",
            "Укажите название коллекции.",
        ),
        ("media_item_not_found", "Title not found.", "Тайтл не найден."),
        ("collection_unavailable", "The collection is unavailable.", "Коллекция недоступна."),
        ("collection_not_found", "Collection not found.", "Коллекция не найдена."),
        (
            "metadata_selection_expired",
            "The metadata selection expired. Search again.",
            "Срок действия выбора метаданных истёк. Выполните поиск снова.",
        ),
        (
            "metadata_provider_unavailable",
            "The metadata provider is unavailable.",
            "Поставщик метаданных недоступен.",
        ),
        (
            "metadata_provider_not_configured",
            "The metadata provider is not configured.",
            "Поставщик метаданных не настроен.",
        ),
        (
            "metadata_provider_not_found",
            "Metadata provider not found.",
            "Поставщик метаданных не найден.",
        ),
        (
            "metadata_provider_configuration_invalid",
            "Metadata provider configuration is invalid.",
            "Конфигурация поставщика метаданных неверна.",
        ),
        ("manual_import_invalid", "Manual metadata is invalid.", "Ручные метаданные неверны."),
        ("prowlarr_not_configured", "Prowlarr is not configured.", "Prowlarr не настроен."),
        ("prowlarr_search_failed", "Torrent search failed.", "Поиск торрентов не удался."),
        (
            "prowlarr_configuration_invalid",
            "Prowlarr configuration is invalid.",
            "Конфигурация Prowlarr неверна.",
        ),
        (
            "prowlarr_api_key_reference_required",
            "A Prowlarr API key environment reference is required.",
            "Укажите ссылку на переменную окружения с API-ключом Prowlarr.",
        ),
        (
            "prowlarr_base_url_invalid",
            "The Prowlarr base URL is invalid.",
            "Базовый URL Prowlarr неверен.",
        ),
        (
            "prowlarr_download_origin_rejected",
            "The torrent download origin was rejected.",
            "Источник загрузки торрента отклонён.",
        ),
        (
            "prowlarr_download_failed",
            "The torrent download failed.",
            "Загрузка торрента не удалась.",
        ),
        ("release_search_query_required", "Enter a search query.", "Введите поисковый запрос."),
        (
            "release_search_token_expired",
            "The release selection expired. Search again.",
            "Срок действия выбранного релиза истёк. Выполните поиск снова.",
        ),
        (
            "download_client_unavailable",
            "The download client is unavailable.",
            "Клиент загрузки недоступен.",
        ),
        ("download_client_not_found", "Download client not found.", "Клиент загрузки не найден."),
        (
            "download_client_archived",
            "The download client is archived.",
            "Клиент загрузки находится в архиве.",
        ),
        (
            "download_client_configuration_invalid",
            "Download client configuration is invalid.",
            "Конфигурация клиента загрузки неверна.",
        ),
        (
            "download_client_module_unknown",
            "Unknown download client module.",
            "Неизвестный модуль клиента загрузки.",
        ),
        (
            "download_client_destinations_unavailable",
            "Download destinations are unavailable.",
            "Папки назначения недоступны.",
        ),
        (
            "download_client_authentication_failed",
            "Download client authentication failed.",
            "Не удалось аутентифицироваться в клиенте загрузки.",
        ),
        (
            "download_client_submission_failed",
            "The download client submission failed.",
            "Не удалось передать загрузку клиенту.",
        ),
        (
            "download_client_correlation_mismatch",
            "The download client returned an unexpected correlation.",
            "Клиент загрузки вернул неожиданную корреляцию.",
        ),
        (
            "download_client_rejected",
            "The download client rejected the submission.",
            "Клиент загрузки отклонил загрузку.",
        ),
        (
            "download_artifact_unsupported",
            "This download artifact is unsupported.",
            "Этот артефакт загрузки не поддерживается.",
        ),
        (
            "correlation_lookup_inconclusive",
            "The submission status could not be confirmed.",
            "Не удалось подтвердить статус отправки.",
        ),
        ("acquisition_unavailable", "Acquisition is unavailable.", "Получение недоступно."),
        (
            "acquisition_reference_not_found",
            "The acquisition reference was not found.",
            "Ссылка на получение не найдена.",
        ),
        (
            "acquisition_revision_mismatch",
            "The acquisition revision does not match the title.",
            "Ревизия получения не соответствует тайтлу.",
        ),
        ("acquisition_not_found", "Acquisition not found.", "Получение не найдено."),
        (
            "download_destination_unavailable",
            "The selected download destination is unavailable.",
            "Выбранная папка назначения недоступна.",
        ),
        ("submission_timeout", "The submission timed out.", "Истекло время ожидания отправки."),
        (
            "submission_timeout_not_found",
            "The timed-out submission was not found.",
            "Отправка с истекшим временем ожидания не найдена.",
        ),
        (
            "manual_reconcile_not_found",
            "The acquisition was not found during reconciliation.",
            "При сверке получение не найдено.",
        ),
        (
            "session_secret_too_short",
            "The session secret is too short.",
            "Секрет сеанса слишком короткий.",
        ),
        ("invalid_session", "The session is invalid.", "Сеанс недействителен."),
        (
            "env_reference_invalid",
            "The environment reference is invalid.",
            "Ссылка на переменную окружения неверна.",
        ),
        (
            "env_reference_unresolved",
            "The referenced environment variable is not set.",
            "Указанная переменная окружения не задана.",
        ),
        (
            "naming_profile_unsupported",
            "The naming profile is unsupported.",
            "Профиль именования не поддерживается.",
        ),
        (
            "naming_entity_mismatch",
            "The naming entity does not match.",
            "Сущность именования не соответствует данным.",
        ),
        (
            "naming_selector_invalid",
            "The naming selector is invalid.",
            "Селектор именования неверен.",
        ),
        (
            "target_extension_invalid",
            "The target extension is invalid.",
            "Целевое расширение неверно.",
        ),
        (
            "nfo_entity_mismatch",
            "The NFO entity does not match.",
            "Сущность NFO не соответствует данным.",
        ),
        ("nfo_selector_invalid", "The NFO selector is invalid.", "Селектор NFO неверен."),
        (
            "nfo_multi_episode_unsupported",
            "Multi-episode NFO output is unsupported.",
            "Вывод NFO для нескольких серий не поддерживается.",
        ),
        (
            "manual_external_id_invalid",
            "The Manual external ID is invalid.",
            "Внешний ID Manual неверен.",
        ),
        (
            "revision_override_fields_invalid",
            "The revision override contains unsupported fields.",
            "Переопределение ревизии содержит неподдерживаемые поля.",
        ),
        (
            "revision_override_invalid",
            "The revision override is invalid.",
            "Переопределение ревизии неверно.",
        ),
        (
            "provider_identity_mismatch",
            "The provider identity does not match the title.",
            "Идентификатор поставщика не соответствует тайтлу.",
        ),
    ],
)
def test_all_stable_ui_codes_have_english_and_russian_messages(
    code: str, english: str, russian: str
) -> None:
    from media_finder.ui_i18n import message_for

    assert message_for(code, "en") == english
    assert message_for(code, "ru") == russian


def test_unknown_code_has_a_safe_localized_fallback() -> None:
    from media_finder.ui_i18n import message_for

    assert message_for("future_error", "en") == "A safely hidden error occurred."
    assert message_for("future_error", "ru") == "Произошла безопасно скрытая ошибка."


def test_exception_mapping_preserves_only_known_explicit_module_codes() -> None:
    from media_finder.sdk.errors import ModuleError
    from media_finder.ui_i18n import code_for_exception

    assert (
        code_for_exception(
            ModuleError(code="download_client_rejected", message="unsafe upstream prose"),
            "acquisition_unavailable",
        )
        == "download_client_rejected"
    )
    assert code_for_exception(RuntimeError("unsafe upstream prose"), "acquisition_unavailable") == (
        "acquisition_unavailable"
    )


@pytest.mark.parametrize(
    ("kind", "status", "russian_kind", "russian_status"),
    [
        ("movie", "pending", "Фильм", "Ожидает отправки"),
        ("series", "submitted", "Сериал", "Отправлено"),
        ("series", "failed", "Сериал", "Не удалось отправить"),
    ],
)
def test_kind_and_acquisition_status_are_localized(
    kind: str, status: str, russian_kind: str, russian_status: str
) -> None:
    from media_finder.ui_i18n import acquisition_status_label, media_kind_label

    assert media_kind_label(kind, "en") == kind.title()
    assert media_kind_label(kind, "ru") == russian_kind
    assert acquisition_status_label(status, "ru") == russian_status


def test_module_translation_assets_resolve_keys_with_locale_fallback() -> None:
    from media_finder.ui_i18n import module_translation

    assert module_translation("tmdb", "module.tmdb.settings.base_url", "ru") == "Базовый адрес API"
    assert module_translation("qbittorrent", "module.qbittorrent.password_ref", "ru") == (
        "Ссылка на переменную среды с паролем"
    )
    assert module_translation("manual", "module.manual.name", "en") == "Manual"
    assert module_translation("manual", "missing.key", "ru") == "missing.key"
