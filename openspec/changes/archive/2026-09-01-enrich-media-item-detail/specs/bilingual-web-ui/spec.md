## MODIFIED Requirements

### Requirement: Media detail navigation
A media-item page SHALL present the saved normalized overview and a `Find release` action. The overview SHALL retain the localized display title, media type, metadata provider, and plot or localized no-plot state, and SHALL additionally present every available release year, original title, genre, and poster according to the rules below.

The interface SHALL trim the original title and each genre label for presentation, omit an original title or genre whose trimmed value is empty, and preserve the stored relative order of the remaining genres. It SHALL display an available original title even when it equals the localized display title, and SHALL omit absent optional values without rendering an empty metadata row.

The poster candidate SHALL be the first normalized artwork entry whose kind equals `poster` case-insensitively. The interface SHALL treat that poster as informative content, assign its complete untrusted module-normalized HTTP(S) URL unchanged, load it lazily with no referrer, and give it a localized accessible name that identifies the displayed work. The interface SHALL NOT construct, rewrite, origin-filter, proxy, or server-fetch the URL. A URL accepted by the normalized artwork contract MAY address a public, loopback, private-network, or userinfo-bearing origin; the direct request SHALL NOT be represented as private or origin-restricted. When poster artwork is absent or fails to load, the interface SHALL replace it with a stable poster-shaped local fallback carrying a localized unavailable-image name and SHALL NOT request a remote fallback asset.

The poster and metadata SHALL form one responsive detail composition that preserves all metadata and actions without horizontal page overflow at supported mobile widths. A Manual item SHALL additionally provide an edit action that opens its structured Manual editor. A provider-backed item SHALL NOT expose that action. The built-in interface SHALL NOT expose Acquisition-history views, and SHALL expose season and episode hierarchy only while creating or editing Manual metadata.

#### Scenario: Review a rich saved item
- **WHEN** a saved item has poster artwork, original title, release year, genres, and plot
- **THEN** the detail page displays the first case-insensitive poster artwork, the original title, year, every non-empty trimmed genre in stored order, and the plot alongside its existing identity context and actions

#### Scenario: Omit absent or whitespace-only detail values
- **WHEN** original title is absent or whitespace-only, release year is absent, genres are empty or whitespace-only, and poster artwork is absent
- **THEN** the detail page renders no empty original-title, year, or genre row and shows the localized local poster fallback without hiding the remaining overview or actions

#### Scenario: Load untrusted stored artwork directly
- **WHEN** the first normalized poster contains any complete HTTP(S) URL accepted by the current artwork contract
- **THEN** the page assigns that exact URL unchanged to a lazy informative image with no referrer and does not construct, rewrite, origin-filter, proxy, or server-fetch it

#### Scenario: Replace failed detail artwork locally
- **WHEN** the selected poster URL fails to load
- **THEN** the page replaces it with the localized informative local fallback without requesting a remote fallback or removing metadata and actions

#### Scenario: Browse rich detail on mobile
- **WHEN** a user opens a rich media-item page at a supported mobile width
- **THEN** the poster, metadata, `Find release`, and any permitted Manual edit action remain available without horizontal document scrolling

#### Scenario: Open a series
- **WHEN** a user opens a series card whose provider is not Manual
- **THEN** the detail page exposes its rich normalized overview and release-search action without an editable season hierarchy or Manual edit action

#### Scenario: Open a Manual series
- **WHEN** a user opens a Manual series
- **THEN** the detail page exposes its rich normalized overview, release-search action, and an edit action whose editor can represent the current seasons, episodes, and Season 00 specials
