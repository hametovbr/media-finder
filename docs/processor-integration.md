# Processor integration guide

FileFlows, n8n, and custom processors can use Media Finder as a metadata and naming control plane. The processor remains the only component that reads, remuxes, renames, or moves downloaded files. Media Finder does not need filesystem mounts.

## Authentication and revision choice

Every `/api/v1/*` request requires the integration token as a Bearer credential:

```http
Authorization: Bearer <MEDIA_FINDER_INTEGRATION_TOKEN>
```

Use an Acquisition endpoint while processing a submitted release. It resolves the immutable revision pinned when that release was selected, so later edits cannot change an in-flight result. Use a media-item endpoint only for an explicit current-catalog operation.

| Purpose | Current catalog revision | Acquisition-pinned revision |
| --- | --- | --- |
| Normalized metadata | `GET /api/v1/media-items/{item_id}/metadata` | `GET /api/v1/acquisitions/{acquisition_id}/metadata` |
| Jellyfin naming | `GET /api/v1/media-items/{item_id}/exports/naming` | `GET /api/v1/acquisitions/{acquisition_id}/exports/naming` |
| Jellyfin/Kodi NFO | `GET /api/v1/media-items/{item_id}/exports/nfo` | `GET /api/v1/acquisitions/{acquisition_id}/exports/nfo` |

Metadata responses contain the versioned normalized effective snapshot and never the provider's raw response.

## Naming requests

The fixed profile is `jellyfin-v1`. The `target_extension` is optional and is caller data: Media Finder does not assume MKV or any other container. Omit it to receive a stem/path without an extension.

```console
curl --get http://media-finder:8080/api/v1/acquisitions/ACQUISITION_ID/exports/naming \
  --header "Authorization: Bearer $MEDIA_FINDER_INTEGRATION_TOKEN" \
  --data-urlencode entity_type=episode \
  --data-urlencode season_number=1 \
  --data-urlencode episode_numbers=1 \
  --data-urlencode episode_numbers=2 \
  --data-urlencode target_extension=webm
```

Valid selectors are:

- `movie` and `tvshow`: no season or episode selector;
- `season`: one `season_number`, including `0` for specials;
- `episode`: one `season_number` and one or more contiguous repeated `episode_numbers` values.

The JSON result supplies `relative_directory`, `basename`, optional `target_extension`, final `relative_path`, and `nfo_filename`. A processor should use these returned values directly instead of reimplementing sanitation.

## NFO requests

NFO output is structured Jellyfin/Kodi-compatible XML:

```console
curl --get http://media-finder:8080/api/v1/acquisitions/ACQUISITION_ID/exports/nfo \
  --header "Authorization: Bearer $MEDIA_FINDER_INTEGRATION_TOKEN" \
  --data-urlencode entity_type=episode \
  --data-urlencode season_number=0 \
  --data-urlencode episode_numbers=1 \
  --output episode.nfo
```

Supported entities are `movie`, `tvshow`, `season`, and one `episode`. Naming supports a contiguous multi-episode file, but NFO deliberately rejects multiple episodes with HTTP `422` and code `nfo_multi_episode_unsupported`; split the episodes before requesting their NFO files.

## Retention and warnings

Provider modules own their retention rules. An expired source returns HTTP `410` with code `metadata_source_expired` for metadata, naming, and NFO, including acquisition-pinned revisions. The processor must stop rather than fabricate or reuse stale metadata.

Before expiry, a provider may attach `Warning`, `Sunset`, and `X-Media-Finder-Metadata-Expires` headers to NFO responses. Preserve these in processor logs or workflow state when operationally useful. Media Finder creates no provenance sidecar. If an operator persists a TMDB-derived NFO beyond Media Finder's provider-cache retention window, long-term storage and compliance are the operator's responsibility.

## Errors and request correlation

Errors use one safe envelope:

```json
{
  "error": {
    "code": "request_validation_failed",
    "request_id": "b2169b82-b47e-4f21-a025-284576305503",
    "details": {}
  }
}
```

Send a safe `X-Request-ID` to correlate a workflow run, or record the generated response header. Stable codes processors should branch on include `authentication_required`, `media_item_not_found`, `acquisition_not_found`, `metadata_revision_not_found`, `metadata_source_expired`, `request_validation_failed`, `nfo_multi_episode_unsupported`, and `internal_error`. Do not parse human prose or expose the Bearer token in URLs, node labels, logs, or diagnostic output.

## Workflow patterns

For FileFlows, use an HTTP node after media identification to fetch acquisition-pinned metadata, then call naming after the final container extension is known, and finally request the appropriate NFO entity. For n8n, use HTTP Request nodes with a credential-backed Authorization header and route by HTTP status plus `error.code`. A generic processor should use the same sequence:

1. receive the Media Finder Acquisition UUID through the download-client correlation tag `mf-acq-UUID`;
2. fetch the pinned metadata and identify the concrete movie, season, or episode selector;
3. perform any external mux/remux work and determine the resulting extension;
4. request naming with that extension;
5. request one NFO per supported entity and write the returned XML beside the final media file.

Retry only transport failures that are known to be safe. A `4xx` response describes a deterministic request or source-state problem and requires corrected input or operator action.
