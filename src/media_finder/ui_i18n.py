"""Gettext-backed labels for safe browser-facing codes and module assets."""

from __future__ import annotations

import gettext
import json
from functools import cache
from pathlib import Path

LOCALE_ROOT = Path(__file__).with_name("locales")

_SOURCES = {
    "csrf_invalid": "Request rejected.",
    "ui_form_too_large": "The submitted form is too large.",
    "collection_name_required": "A collection name is required.",
    "media_item_not_found": "Title not found.",
    "collection_unavailable": "The collection is unavailable.",
    "collection_not_found": "Collection not found.",
    "metadata_selection_expired": "The metadata selection expired. Search again.",
    "metadata_provider_unavailable": "The metadata provider is unavailable.",
    "metadata_provider_not_configured": "The metadata provider is not configured.",
    "metadata_provider_not_found": "Metadata provider not found.",
    "metadata_provider_configuration_invalid": "Metadata provider configuration is invalid.",
    "manual_import_invalid": "Manual metadata is invalid.",
    "manual_item_not_found": "Manual title not found.",
    "manual_draft_expired": "The Manual metadata draft expired.",
    "prowlarr_not_configured": "Prowlarr is not configured.",
    "prowlarr_search_failed": "Torrent search failed.",
    "prowlarr_configuration_invalid": "Prowlarr configuration is invalid.",
    "prowlarr_api_key_reference_required": (
        "A Prowlarr API key environment reference is required."
    ),
    "prowlarr_base_url_invalid": "The Prowlarr base URL is invalid.",
    "prowlarr_download_origin_rejected": "The torrent download origin was rejected.",
    "prowlarr_download_failed": "The torrent download failed.",
    "prowlarr_response_too_large": "The torrent search response is too large.",
    "prowlarr_result_limit_exceeded": "The torrent search returned too many results.",
    "prowlarr_torrent_too_large": "The torrent artifact is too large.",
    "release_search_query_required": "Enter a search query.",
    "release_search_token_expired": "The release selection expired. Search again.",
    "download_client_unavailable": "The download client is unavailable.",
    "download_client_not_found": "Download client not found.",
    "download_client_configuration_invalid": "Download client configuration is invalid.",
    "download_client_module_unknown": "Unknown download client module.",
    "download_client_destinations_unavailable": "Download destinations are unavailable.",
    "download_client_authentication_failed": "Download client authentication failed.",
    "download_client_submission_failed": "The download client submission failed.",
    "download_client_correlation_mismatch": (
        "The download client returned an unexpected correlation."
    ),
    "download_client_rejected": "The download client rejected the submission.",
    "download_artifact_unsupported": "This download artifact is unsupported.",
    "correlation_lookup_inconclusive": "The submission status could not be confirmed.",
    "acquisition_unavailable": "Acquisition is unavailable.",
    "acquisition_reference_not_found": "The acquisition reference was not found.",
    "acquisition_revision_mismatch": "The acquisition revision does not match the title.",
    "acquisition_not_found": "Acquisition not found.",
    "download_destination_unavailable": "The selected download destination is unavailable.",
    "submission_timeout": "The submission timed out.",
    "submission_timeout_not_found": "The timed-out submission was not found.",
    "manual_reconcile_not_found": "The acquisition was not found during reconciliation.",
    "session_secret_too_short": "The session secret is too short.",
    "invalid_session": "The session is invalid.",
    "env_reference_invalid": "The environment reference is invalid.",
    "env_reference_unresolved": "The referenced environment variable is not set.",
    "naming_profile_unsupported": "The naming profile is unsupported.",
    "naming_entity_mismatch": "The naming entity does not match.",
    "naming_selector_invalid": "The naming selector is invalid.",
    "target_extension_invalid": "The target extension is invalid.",
    "nfo_entity_mismatch": "The NFO entity does not match.",
    "nfo_selector_invalid": "The NFO selector is invalid.",
    "nfo_multi_episode_unsupported": "Multi-episode NFO output is unsupported.",
    "manual_external_id_invalid": "The Manual external ID is invalid.",
    "revision_override_fields_invalid": ("The revision override contains unsupported fields."),
    "revision_override_invalid": "The revision override is invalid.",
    "provider_identity_mismatch": "The provider identity does not match the title.",
}

_UNKNOWN = "A safely hidden error occurred."
_KINDS = {"movie": "Movie", "series": "Series"}
_STATUSES = {
    "pending": "Pending submission",
    "submitted": "Submitted",
    "failed": "Submission failed",
}


@cache
def _translation(locale: str) -> gettext.NullTranslations:
    selected = "ru" if locale == "ru" else "en"
    return gettext.translation("messages", LOCALE_ROOT, languages=[selected], fallback=True)


def message_for(code: str, locale: str) -> str:
    """Return the safe human-facing message for a stable code."""

    return _translation(locale).gettext(_SOURCES.get(code, _UNKNOWN))


def code_for_exception(error: Exception, default: str) -> str:
    """Preserve only known stable codes; never expose arbitrary exception text."""

    explicit = getattr(error, "code", None)
    candidate = explicit if isinstance(explicit, str) else str(error)
    return candidate if candidate in _SOURCES else default


def media_kind_label(kind: str, locale: str) -> str:
    return _translation(locale).gettext(_KINDS.get(kind, kind))


def acquisition_status_label(status: str, locale: str) -> str:
    return _translation(locale).gettext(_STATUSES.get(status, status))


@cache
def _module_catalog(module_key: str, locale: str) -> dict[str, str]:
    path = Path(__file__).with_name("modules") / module_key / "translations" / f"{locale}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return (
        payload
        if isinstance(payload, dict)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items())
        else {}
    )


def module_translation(module_key: str, key: str, locale: str) -> str:
    """Resolve a packaged module translation, falling back to its English asset then key."""

    selected = "ru" if locale == "ru" else "en"
    return _module_catalog(module_key, selected).get(key) or _module_catalog(module_key, "en").get(
        key, key
    )
