# Bilingual Web UI Specification

## Purpose

Define an accessible bilingual, bundled browser interface that manages the supported catalog-to-Acquisition workflow exclusively through the same-origin control API.

## Requirements

### Requirement: Manual metadata workflows
The built-in interface SHALL provide structured Manual movie and series creation, complete version-1 Manual JSON import, lossless editing of existing Manual items, and atomic episode CSV import for existing Manual series. The structured editor SHALL support localized titles, common normalized fields, seasons, episodes, and Season 00 specials. It SHALL submit only the existing browser control Manual operations and SHALL NOT create a presentation-owned metadata or persistence path.

When editing an existing Manual item, the interface SHALL preserve its immutable Manual external identifier, SHALL NOT permit its movie or series kind to change, SHALL preserve every normalized field not changed through the structured editor, and SHALL remove a season or episode only when the user deliberately removes that row. A non-Manual item SHALL NOT expose an actionable Manual editor.

#### Scenario: Create a structured Manual movie
- **WHEN** a user enters valid Manual movie fields and optionally selects a collection
- **THEN** the interface submits one complete version-1 Manual document through the control API and opens the resulting catalog item without creating an Acquisition

#### Scenario: Create a Manual series with specials
- **WHEN** a user enters a Manual series containing regular seasons and Season 00 episodes
- **THEN** the interface submits the hierarchy with its explicit season and episode numbers and presents the saved immutable revision

#### Scenario: Import a complete Manual document
- **WHEN** a user supplies a valid complete version-1 Manual JSON document
- **THEN** the interface validates and submits the complete document without dropping supported rich fields or rewriting a supplied valid Manual identity

#### Scenario: Confirm an existing Manual identity
- **WHEN** a Manual import or edit targets an existing Manual identity and the control API returns `confirmation_required` with a valid Manual confirmation token
- **THEN** the interface presents an explicit review step and submits that opaque token only after user confirmation

#### Scenario: Manual confirmation expires
- **WHEN** a Manual confirmation token is consumed, expired, evicted, or invalidated by restart
- **THEN** the interface presents localized safe feedback and requires the originating import or edit to be repeated without replaying the stale token

#### Scenario: Edit a rich Manual revision
- **WHEN** a user changes structured fields after importing a rich Manual document
- **THEN** the interface submits a complete document that applies the visible changes, preserves every unedited normalized field, keeps the existing identity and kind, and removes only deliberately deleted season or episode rows

#### Scenario: Reject editing a non-Manual item
- **WHEN** a user navigates to the edit route for an item whose provider is not Manual
- **THEN** the interface presents localized non-actionable feedback and does not submit a Manual mutation

#### Scenario: Import valid episode CSV
- **WHEN** a user submits a valid bounded episode CSV document for a Manual series
- **THEN** the interface applies all rows through one atomic control operation and presents the resulting revision

#### Scenario: Reject invalid episode CSV
- **WHEN** any row in an episode CSV document is invalid
- **THEN** the interface presents localized safe validation feedback and no partial episode update is shown or applied

### Requirement: Same-origin control client
The built-in interface SHALL bootstrap its browser session and execute its catalog, provider metadata, Manual metadata, release, destination, and Acquisition workflows exclusively through the same-origin `/api/control/v1` JSON contract. It SHALL send the session CSRF token and JSON media type on mutations, SHALL NOT call the processor `/api/v1` surface, and SHALL NOT receive a processor integration token, backend service, repository, database object, or concrete integration instance.

#### Scenario: Bootstrap the built-in client
- **WHEN** a browser opens the built-in interface without an existing valid session
- **THEN** the interface obtains its supported locales, selected locale preferences, and CSRF token from `/api/control/v1/session` while the signed session cookie remains HttpOnly

#### Scenario: Submit a protected mutation
- **WHEN** the user confirms provider metadata, Manual metadata, or Acquisition submission
- **THEN** the interface sends same-origin JSON with the current session CSRF token and the backend applies the existing control-contract behavior

#### Scenario: Inspect browser traffic
- **WHEN** the supported built-in workflows are exercised in a browser
- **THEN** no request targets `/api/v1` and no processor Bearer credential is present in browser state or traffic

### Requirement: Supported built-in workflow
The built-in interface SHALL expose catalog browsing, read-only collection filtering, media overview, metadata-provider search and explicit selection, Manual create, edit, JSON import, and episode CSV import, release search and explicit selection, live destination selection, and idempotent Acquisition submission. It SHALL NOT expose general collection or catalog-item archive, restore, or move controls; Acquisition history or reconciliation controls; integration diagnostics; Settings; or About. The omitted workflows SHALL remain available through their unchanged browser control API operations for future interfaces and later increments.

#### Scenario: Complete the supported path
- **WHEN** a user browses the catalog, selects provider metadata, chooses a release and current destination, and confirms submission
- **THEN** the interface completes the path through `/api/control/v1` and presents the resulting Acquisition state without requiring an omitted secondary workflow

#### Scenario: Complete a Manual path
- **WHEN** a user creates or imports valid Manual metadata and declines `Find release`
- **THEN** the interface saves and opens the Manual catalog item without creating an Acquisition

#### Scenario: Open an omitted secondary route
- **WHEN** a user navigates to a removed route for Settings, diagnostics, About, catalog mutation, or Acquisition reconciliation
- **THEN** the client presents localized not-found feedback and does not invoke a legacy HTML handler or mutate state

### Requirement: Responsive catalog shell
The UI SHALL provide a desktop-first responsive shell with read-only collection navigation, `Uncategorized`, an add-title action, and a poster-grid main view. Desktop navigation SHALL remain visible beside the catalog, while a mobile viewport SHALL expose the same navigation through a keyboard-operable dismissible drawer without horizontal page overflow.

#### Scenario: Browse a collection
- **WHEN** a user selects an existing collection
- **THEN** the main view shows its active media cards in a responsive poster grid

#### Scenario: Browse on a mobile viewport
- **WHEN** a user opens and closes catalog navigation on a supported mobile viewport
- **THEN** focus moves predictably, every supported navigation action remains available, and the document does not require horizontal scrolling

#### Scenario: Poster artwork is absent or cannot load
- **WHEN** a catalog item has no normalized poster artwork or its external image fails
- **THEN** its card retains a stable poster-shaped local placeholder without requesting a remote fallback asset

### Requirement: Informative media cards
Each media card SHALL show title, year, media type, metadata provider, and the latest Acquisition state as `pending`, `submitted`, or `failed` when an attempt exists. A `pending` card SHALL indicate that manual reconciliation may be required and SHALL NOT imply client download progress. Cards SHALL NOT display download progress for any state.

#### Scenario: Acquisition remains pending
- **WHEN** an item's latest acquisition is pending manual reconciliation
- **THEN** the card shows `pending` with a manual-reconciliation indication without inventing download progress or exposing a reconciliation control in the supported built-in interface

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

### Requirement: Explicit add workflow
Adding an item SHALL begin with an explicit choice between metadata-provider search and Manual entry or import. The provider path SHALL continue through provider-scoped result selection and any required similarity confirmation, save the catalog item, and only then offer an optional `Find release` action. Results from different metadata providers SHALL be grouped separately and SHALL NOT be automatically merged. The Manual path SHALL follow the Manual metadata workflow and SHALL NOT search or impersonate an external provider.

#### Scenario: Add without downloading
- **WHEN** a user confirms provider metadata and declines `Find release`
- **THEN** the catalog item is saved without creating an Acquisition

#### Scenario: Select one provider result
- **WHEN** providers return similar results
- **THEN** the UI identifies each provider and requires one explicit selection

#### Scenario: Metadata selection expires
- **WHEN** a metadata selection token is expired, consumed, evicted, or invalidated by restart
- **THEN** the interface displays localized safe feedback and returns the user to metadata search without replaying the stale selection

#### Scenario: Choose Manual entry
- **WHEN** a user selects the Manual option from the add workflow
- **THEN** the interface opens the Manual create/import route without issuing a provider search

### Requirement: Preview-rich metadata result selection
The built-in metadata-search interface SHALL render each provider result as a row containing its existing identity context, a poster or stable local poster fallback, its optional description as plain text, and a localized row-level `Select` action. It SHALL NOT require a radio selection or a separate footer save action. Activating a row action SHALL immediately invoke the existing metadata-selection mutation and continue to the same saved-item or similarity-confirmation outcome. Selection SHALL be globally single-flight across the result set: the initiating row SHALL indicate progress, every result action SHALL remain disabled until the request settles, and a recoverable failure SHALL re-enable the actions without replaying or duplicating the mutation.

Remote result posters SHALL use the complete module-produced URL unchanged, lazy loading, and a no-referrer policy. A missing or failed poster SHALL use the established local fallback without requesting a remote fallback asset. The result list SHALL remain keyboard operable, visibly focused, semantically announced, localized in English and Russian, and free of horizontal page overflow at supported mobile widths.

#### Scenario: Review enriched provider results
- **WHEN** metadata search returns results with poster and description previews
- **THEN** each provider-grouped row displays its preview as plain text and one localized `Select` action without a radio control or footer save action

#### Scenario: Show absent or failed previews
- **WHEN** a result has no description or its poster is absent or fails to load
- **THEN** the row remains selectable, omits the absent description without an empty interactive region, and retains a stable local poster fallback

#### Scenario: Load a direct provider poster safely
- **WHEN** a result has a valid complete poster URL
- **THEN** the browser requests that exact URL lazily with no referrer and the UI neither constructs nor rewrites it

#### Scenario: Select a result immediately
- **WHEN** the user activates a row's `Select` action once
- **THEN** the UI sends one existing selection mutation and continues to the same saved-item or required similarity-confirmation outcome without another confirmation click for ordinary selection

#### Scenario: Prevent parallel selections
- **WHEN** a selection request is pending and the user attempts to activate any result action again
- **THEN** only the original mutation exists, the initiating row shows pending state, and every result action remains disabled until the request settles

#### Scenario: Recover from a selection failure
- **WHEN** the selection request fails with a recoverable error
- **THEN** the UI presents localized semantic feedback and re-enables all result actions without automatically replaying the request

#### Scenario: Confirm a similar item
- **WHEN** selection returns a similarity-confirmation result with an opaque confirmation token
- **THEN** the UI presents the existing explicit review step and submits that returned token only after user confirmation

#### Scenario: Similarity confirmation expires
- **WHEN** the similarity-confirmation token is consumed, expired, evicted, or invalidated by restart
- **THEN** the UI presents localized safe feedback and returns to metadata search without replaying the stale token

#### Scenario: Select a result on a mobile keyboard workflow
- **WHEN** a keyboard-only user operates the result list at a supported mobile width
- **THEN** every row action is reachable with visible focus, status changes are semantically announced, and the page does not require horizontal scrolling

### Requirement: Explicit release submission UI
The release-search UI SHALL accept a free query and optional Prowlarr indexer identifiers, then require explicit selection of a release and a live qBittorrent destination. The sole environment-owned qBittorrent instance SHALL be selected implicitly and SHALL NOT be configurable through the UI.

#### Scenario: Search selected Prowlarr indexers
- **WHEN** a user supplies one or more valid Prowlarr indexer identifiers with a release query
- **THEN** the UI submits those identifiers through the existing browser control release-search operation and keeps release selection explicit

#### Scenario: Search all Prowlarr indexers
- **WHEN** a user submits a release query without indexer identifiers
- **THEN** the UI searches without an indexer restriction

#### Scenario: Submit selected release
- **WHEN** a user selects a release and current destination and confirms
- **THEN** the UI initiates one idempotent Acquisition tied to the current metadata revision and the environment-owned qBittorrent identity

#### Scenario: qBittorrent is unavailable
- **WHEN** the environment-owned qBittorrent instance cannot be constructed or validated, or its live destinations cannot be loaded
- **THEN** the release UI reports a localized safe diagnostic and does not offer stale persisted clients or an actionable submission control

#### Scenario: Archive and restore a download-client instance
- **WHEN** a caller attempts to archive or restore a download-client instance through a former UI route
- **THEN** the request is rejected because the environment-owned qBittorrent identity has no user-managed lifecycle

### Requirement: Localized and accessible interaction
All human-readable UI text SHALL be localizable in English and Russian. For an API or domain error, the UI SHALL select a localized human-readable message by its stable invariant machine error code. Machine error codes SHALL remain language-neutral, stable, and byte-for-byte unchanged across locales and SHALL never be translated. Critical flows SHALL support keyboard navigation, visible focus, associated labels, and semantic status feedback.

#### Scenario: Switch interface language
- **WHEN** a user selects Russian
- **THEN** subsequent UI pages use Russian localization while developer documentation and persisted provider identifiers remain unchanged

#### Scenario: Complete add flow by keyboard
- **WHEN** a keyboard-only user adds and confirms an item
- **THEN** every required control is reachable and the result is announced through semantic feedback

#### Scenario: Localize an error message
- **WHEN** the same stable machine error code is presented in English and Russian UI locales
- **THEN** the human-readable message uses the selected locale while the machine error code is identical in both responses and diagnostic context

#### Scenario: Unknown machine error code
- **WHEN** the UI receives an unrecognized stable machine error code
- **THEN** it displays a localized generic safe error message while retaining the unchanged code for diagnostics

### Requirement: External-auth trust and CSRF protection
The UI SHALL maintain no user-account database and SHALL rely on external reverse-proxy authentication when exposed beyond localhost. Mutating UI requests SHALL require a valid signed session and CSRF token. Session cookies SHALL be `HttpOnly`, `SameSite=Lax`, and configurable as `Secure` for HTTPS.

#### Scenario: Missing CSRF token
- **WHEN** a browser submits a mutating UI request without a valid CSRF token
- **THEN** the system rejects the request without applying changes

#### Scenario: HTTPS deployment
- **WHEN** the operator enables secure-cookie mode behind an HTTPS reverse proxy
- **THEN** the session cookie includes the `Secure` attribute

### Requirement: Independently buildable built-in interface
The bundled interface SHALL be delivered as a separately buildable package whose browser source consumes the deterministic public control OpenAPI contract and presentation libraries only. It SHALL NOT require database, persistence-model, domain-service, runtime-integration, metadata-provider, download-client, backend repository, or processor SDK imports. Its deterministic development mode SHALL render the supported built-in workflow, including Manual create, edit, import, confirmation, and validation states, English and Russian states, responsive layouts, and safe errors with typed fake HTTP responses and no database or external integration.

#### Scenario: Develop the interface in isolation
- **WHEN** a contributor starts the built-in UI development host without Media Finder storage or integration variables
- **THEN** the client renders deterministic catalog, provider metadata, Manual metadata, release, Acquisition, confirmation, validation-error, English, Russian, desktop, and mobile states using the same serialized control shapes used in production

#### Scenario: Violate the package boundary
- **WHEN** built-in UI source imports a prohibited backend, processor, persistence, SDK, or integration package
- **THEN** an automated architecture check rejects the build

#### Scenario: Control schema changes
- **WHEN** the checked-in control OpenAPI document changes without regenerating the built-in client's typed contract
- **THEN** deterministic frontend verification rejects the drift

### Requirement: Built-in interface compatibility
The built-in interface SHALL preserve GET navigation for `/`, `/add`, `/add/manual`, `/items/{item_id}`, `/items/{item_id}/edit`, and `/items/{item_id}/releases` as client routes with equivalent supported outcomes. Removed server-rendered form actions, fragment endpoints, and secondary HTML routes SHALL NOT remain as a parallel presentation path. Their removal SHALL NOT alter the backend control, processor, persistence, or integration semantics.

#### Scenario: Use an existing bookmark and form workflow
- **WHEN** a user upgrades across the built-in UI replacement boundary, opens a supported bookmark, or submits a formerly supported server-rendered form
- **THEN** the GET bookmark renders the corresponding client route, while the removed form submission is rejected without changing state and the supported operation remains available through `/api/control/v1`

#### Scenario: Use a supported bookmark
- **WHEN** a user opens a catalog, provider-add, Manual-add, item-detail, Manual-edit, or release-selection bookmark
- **THEN** the built-in client renders the corresponding supported route and obtains its state from the browser control API

#### Scenario: Submit a legacy form action
- **WHEN** a caller submits a removed Jinja or HTMX form or fragment route
- **THEN** the application rejects the unsupported route without invoking a second domain path or changing state

#### Scenario: Compare built-in and control behavior
- **WHEN** a supported built-in workflow and a direct browser control request perform the same catalog, provider metadata, Manual metadata, release, or Acquisition operation
- **THEN** both use the same browser control endpoint and produce the same state transition and invariant machine error code

### Requirement: Recoverable session bootstrap
If the initial browser-session request fails, the UI SHALL render localized safe feedback and a keyboard-operable retry action without requiring a working session or application shell. Retry SHALL only repeat session bootstrap, remain single-flight and preserve the requested route. A successful retry SHALL open that route with the returned session. It SHALL NOT replay any catalog or Acquisition mutation. Before session preferences are available, feedback SHALL use the first English or Russian language in browser language preferences (including regional variants), falling back to English if neither is present. A successful bootstrap SHALL replace this provisional language with the returned session language.

#### Scenario: Initial session request fails and recovers
- **WHEN** the initial session request fails and the user explicitly retries after the service recovers
- **THEN** the UI shows a safe error followed by pending feedback and opens the originally requested route after one successful retry

#### Scenario: Pre-session feedback language
- **WHEN** bootstrap fails before session preferences are available
- **THEN** feedback uses the first supported browser language, recognizes regional variants such as ru-RU and en-GB, and falls back to English for missing or unsupported preferences

#### Scenario: Repeated bootstrap failure
- **WHEN** retry fails again or is activated repeatedly while pending
- **THEN** the UI retains an actionable failure state after settlement, starts no concurrent retry and never displays credentials or raw response content

### Requirement: Recoverable metadata-provider discovery
Provider discovery SHALL distinguish loading, failure, no available providers and availability. Failed discovery SHALL NOT retry automatically. Failure SHALL expose localized retry; failure or an empty provider list SHALL NOT expose an actionable provider search. The Manual route SHALL remain available. Successful discovery retry SHALL preserve the current route and user-entered query.

#### Scenario: Provider discovery fails
- **WHEN** loading available metadata providers fails
- **THEN** the user sees a localized error, a retry action and the Manual alternative, and cannot submit provider search until discovery succeeds with at least one provider

#### Scenario: No metadata providers are available
- **WHEN** discovery succeeds with an empty provider list
- **THEN** the UI explains that provider search is unavailable and offers Manual entry without reporting a search-result empty state

### Requirement: Explicit search outcomes and recovery
Metadata and release search SHALL distinguish initial, pending, non-empty success, empty success and failure. Empty-result feedback SHALL appear only after a successful search with no results. Pending and completion feedback SHALL identify the submitted query. Failures SHALL use localized safe error messages and retain editable input, including release indexer identifiers.

An explicit retry SHALL repeat the last failed submitted query and its submitted filters. Submitting the search form SHALL use the current editable values. Search requests SHALL be single-flight, without automatic retries. Starting a new search SHALL remove the previous actionable search results and selections; failure SHALL NOT restore them as current results. A response for a superseded or abandoned search SHALL NOT replace the active outcome. Search retry SHALL NOT repeat metadata selection or Acquisition submission.

#### Scenario: Initial and empty states differ
- **WHEN** a user opens either search page and later completes a search with zero results
- **THEN** no empty-result message is shown before the first search and a localized zero-result message identifies the submitted query after success

#### Scenario: Failed search retains input
- **WHEN** metadata or release search fails, including a network failure or unknown error code
- **THEN** the UI displays safe localized feedback, preserves editable fields and offers explicit retry without selecting metadata or submitting an Acquisition

#### Scenario: Retry and edited search have distinct inputs
- **WHEN** a failed search is followed by edits to the input fields
- **THEN** retry repeats the failed submitted values, while form submission searches the newly edited values

#### Scenario: Replace results with a new search
- **WHEN** a user starts a new search after an earlier successful search
- **THEN** previous results and selections cease to be actionable, the new submitted query is identified, and a later failure or abandoned response cannot present old results as the new result

#### Scenario: Pending search remains single-flight
- **WHEN** the user activates search or retry repeatedly while a search is pending
- **THEN** only one search request is issued and pending feedback remains visible until it settles

### Requirement: Recoverable interface-language change
A failed interface-language update SHALL show localized safe feedback in the last confirmed UI language, retain that language and preserve the current route and form values. Explicit retry SHALL request the same failed target language, remain single-flight and never replay unrelated mutations. A successful retry SHALL apply the returned UI locale, update document language and clear the failure feedback. Metadata locale SHALL remain governed by the existing session contract.

#### Scenario: Language change fails and recovers
- **WHEN** an interface-language update fails and the user retries it successfully
- **THEN** the previous UI language and page input remain during failure, the requested language is applied only after success, and no unrelated mutation is repeated

### Requirement: Accessible recovery feedback
All recovery and search-outcome states added by this change SHALL be localized in English and Russian, expose errors as semantic alerts and pending/completion messages as semantic status feedback. Recovery controls SHALL be keyboard reachable with visible focus. Inline feedback SHALL not steal focus from an editable field; replacing a standalone bootstrap failure with the application SHALL place focus predictably in the main content. Feedback SHALL wrap without horizontal document overflow at a 360 CSS-pixel viewport, and recovery controls and text SHALL meet applicable WCAG 2.2 AA contrast and target-size requirements.

#### Scenario: Keyboard recovery in either language
- **WHEN** a keyboard-only user encounters and recovers from a bootstrap, provider, search or language error in English or Russian
- **THEN** errors and status changes are semantically announced, retry remains operable, and focus is neither lost nor moved away from active text entry by inline updates

#### Scenario: Narrow viewport recovery
- **WHEN** recovery feedback contains a long query or localized message at a 360 CSS-pixel viewport
- **THEN** the message and controls remain readable and operable without horizontal document scrolling

### Requirement: Non-destructive Manual list input
The structured Manual editor SHALL preserve the user's exact current text in genres, tags, countries and studios while typing, blurring, changing interface language, disclosing secondary fields or switching away from and back to structured entry. At submission, changed list text SHALL be split on commas, trimmed per entry and stripped of empty entries without adding a quoting grammar. Unedited arrays and all other unedited normalized metadata SHALL remain unchanged, including entries containing commas that arrived through complete JSON import. Raw editor state SHALL NOT appear in the submitted document.

#### Scenario: Type and submit a delimited list
- **WHEN** the user types `Drama, Comedy, ` in a supported list field
- **THEN** the text remains exactly editable through blur and the request contains `Drama` and `Comedy` as two entries only when submitted

#### Scenario: Preserve hidden or inactive input
- **WHEN** the user changes a list, collapses secondary fields, switches entry mode or interface language, and returns
- **THEN** the raw text and other unsaved fields remain unchanged and still participate in dirty detection

#### Scenario: Clear a list without changing other metadata
- **WHEN** the user clears one list or submits a title-only edit of a rich Manual document
- **THEN** the cleared list becomes empty only in the former case, while unedited arrays, rich fields, other-language titles, existing identity and kind remain unchanged

### Requirement: Exclusive Manual page operations
Each Manual create or edit page SHALL permit at most one active mutation across structured submission, JSON import, CSV import and duplicate confirmation. Admission SHALL exclude repeated click or form-submit events before a pending indicator renders. The submitted payload, target and consent to discard another draft SHALL be captured together; inputs, mode changes, conflicting mutations and in-app departure SHALL be blocked during the mutation and its successful completion handling. Pending state SHALL be localized and semantically announced. Mutations SHALL NOT retry automatically.

A duplicate-confirmation step SHALL remain bound to the submitted snapshot and opaque token. It SHALL allow cancellation before confirmation begins, retain all drafts on cancellation/failure, and prevent a second confirmation or dismissal while confirmation is in flight. Expired tokens SHALL be discarded; only a fresh originating operation can obtain another token. Responses from an abandoned page instance SHALL NOT navigate the current page or overwrite its draft.

An alternate-draft discard review SHALL be an exclusive page state bound to its captured operation and consequences. It SHALL block underlying edits, mode changes, file selection, competing mutations and in-app departure until cancelled or accepted. Cancellation SHALL preserve both drafts; acceptance SHALL admit only the captured operation without opening a competing review.

#### Scenario: Keep alternate-draft consent bound to one operation
- **WHEN** an alternate-draft discard review is open and the user attempts to edit, switch modes, select a file, submit another operation or navigate within the app
- **THEN** those actions remain blocked; cancel retains both drafts without a request, and continue admits only the captured payload, target and discard consequences

#### Scenario: Repeat or compete with an active save
- **WHEN** the user submits repeatedly by click or Enter, or attempts another Manual operation while a delayed save/import is active
- **THEN** only the first admitted mutation is sent, its target and payload remain fixed, and localized pending feedback remains available

#### Scenario: Confirm or cancel a submitted snapshot
- **WHEN** the API requests confirmation and the user cancels or confirms the review
- **THEN** cancellation sends no confirmation and preserves drafts, while confirmation sends the captured token once with competing edits and dismissal blocked until settled

#### Scenario: Recover from failure without replay
- **WHEN** a save, import or confirmation fails, including an expired token
- **THEN** the page preserves unsaved input, displays localized safe feedback, releases the pending state and does not automatically repeat a mutation or replay an expired token

### Requirement: Safe Manual file reads
Manual JSON and CSV file loading SHALL coordinate with the owning page's operation state: no mutation SHALL start while an accepted file read is pending, and no new read SHALL start during a mutation or confirmation review. Replacing or clearing a file, editing its text, changing entry mode or abandoning the page SHALL invalidate an older read result. A current valid read SHALL update only its corresponding source text. File errors SHALL retain the previous text and present localized safe feedback without an unhandled rejection; existing import size limits SHALL remain enforced.

#### Scenario: Supersede a file read
- **WHEN** a JSON or CSV file read resolves after a newer selection, clearing the selection, direct text editing, mode change or page departure
- **THEN** the stale result does not overwrite source text, initiate a mutation or affect another page

#### Scenario: Read a current file or encounter a read failure
- **WHEN** the current accepted file finishes reading or fails
- **THEN** only a successful current result replaces its source text; failure preserves the preceding text and releases the read-pending state with safe localized feedback

### Requirement: Explicit destructive Manual edits
Removing an episode, removing a season with its descendants, or changing an unsaved new series with seasons to a movie SHALL require an explicit confirmation describing the affected structure. Cancellation SHALL preserve all values and restore focus to the initiating control. Confirmation SHALL remove only the identified structure and move focus to a remaining relevant control. Existing Manual item identity and kind SHALL remain immutable. A kind change that drops no structure SHALL NOT require a destructive confirmation.

#### Scenario: Remove a season or episode
- **WHEN** the user invokes a season or episode removal
- **THEN** the UI identifies the target and affected descendant count, cancellation changes nothing, and confirmation removes only that target and its descendants

#### Scenario: Change a populated new series to a movie
- **WHEN** the user requests a movie kind for a new series containing seasons
- **THEN** the hierarchy remains intact until explicit confirmation; cancellation retains series kind and all rows, and confirmation changes kind and clears the hierarchy

### Requirement: Protected Manual draft navigation
Dirty detection SHALL include structured fields, raw list text, create collection selection, inactive JSON source and edit CSV source relative to the page's initial or saved draft. Presentation-only row identifiers, disclosure state and interface-language changes SHALL NOT themselves make a draft dirty. Switching entry mode SHALL retain both drafts without a discard prompt.

For a dirty idle page, in-app navigation away SHALL offer stay or explicit discard-and-leave, defaulting focus to stay. Stay SHALL preserve route and every draft value; discard-and-leave SHALL navigate to the intended destination without sending a mutation. Clean navigation SHALL not require confirmation. Confirmed successful operation navigation SHALL be allowed without a second discard prompt only after any unrelated dirty draft was explicitly covered by the user's consent. Navigating to another item's editor SHALL initialize that item's draft rather than reuse the previous draft. Reload/close warnings SHALL be registered only while dirty or busy where browser support permits; the interface SHALL NOT promise draft recovery after browser or operating-system termination and SHALL NOT persist drafts or tokens for this purpose.

#### Scenario: Cancel or accept dirty navigation
- **WHEN** the user follows an app link or a back/forward entry within managed app history from a dirty Manual page
- **THEN** stay preserves all drafts and the current route, while explicit leave reaches the requested destination without a mutation

#### Scenario: Navigate cleanly or after intentional success
- **WHEN** the draft is unchanged or an operation succeeds with all discard consequences already approved
- **THEN** navigation proceeds without a redundant warning and an editor for a different item starts with that item's values

#### Scenario: Register a best-effort unload warning
- **WHEN** draft or busy state enters or leaves a warning-worthy state
- **THEN** a supported browser unload warning is enabled or removed accordingly, with browser-controlled text and no durable draft or token storage

### Requirement: Explicit Manual CSV and alternate-draft consequences
Episode CSV import SHALL operate only on the existing saved Manual series through the unchanged atomic CSV operation. While structured fields differ from that saved draft, CSV submission SHALL be blocked with an explanation to save the form first or explicitly discard its structured changes. A discard-structured action SHALL require confirmation and preserve the CSV source. The UI SHALL NOT automatically chain structured save and CSV import.

If submitting structured create/edit or JSON would leave a different dirty draft behind, the page SHALL identify that draft and require explicit consent before sending the request. Consent SHALL apply to that captured operation only. Cancellation, validation failure, request failure or cancellation of duplicate confirmation SHALL retain both drafts; a later attempt SHALL obtain fresh consent. Successful completion SHALL open the resulting item only after the accepted discard consequences apply. CSV guidance SHALL explain use of the saved revision and all-or-nothing validation in user-facing language.

#### Scenario: Attempt CSV with unsaved structured fields
- **WHEN** the user has edited the form and also entered CSV
- **THEN** CSV import cannot send a request; the explanation exposes a save-first path or explicit structured-discard confirmation, whose acceptance restores the saved form while retaining CSV

#### Scenario: Submit with an alternate dirty draft
- **WHEN** structured submission would discard JSON or CSV text, or JSON import would discard structured changes
- **THEN** a review identifies the draft that successful navigation would discard; cancel sends nothing, and explicit continue sends only the selected operation

#### Scenario: Fail after accepting alternate-draft consequences
- **WHEN** an accepted request fails or its duplicate confirmation is cancelled
- **THEN** both drafts remain available, prior discard consent expires and no second operation starts automatically

### Requirement: Accessible Manual secondary-field disclosure
The Manual editor SHALL keep title, media kind, year, plot and permitted collection selection readily visible, with other common structured fields available through one localized secondary-field disclosure. Closing the disclosure SHALL retain all values. Series creation/editing SHALL retain its existing editable hierarchy and show season/episode counts without adding a read-only hierarchy view. New status text, consequences and actions SHALL support English and Russian, keyboard operation, visible focus and complete labels at 360px and desktop widths without horizontal page overflow. Destructive and draft-discard dialogs SHALL focus their safe action initially and restore or deliberately relocate focus when closed.

#### Scenario: Disclose and hide secondary fields
- **WHEN** the user edits an optional common field and closes then reopens its section
- **THEN** its exact current text is retained, all fields remain reachable by keyboard and hierarchy counts reflect the current draft

#### Scenario: Review consequences on a narrow screen
- **WHEN** a user opens a destructive or draft-discard dialog in English or Russian at 360px width
- **THEN** the target/consequences and complete action labels remain readable without horizontal page scrolling, focus begins on the safe action and keyboard cancellation returns focus predictably

### Requirement: Contextual release search
The release page SHALL show the saved work identity and a link back to its detail page. It SHALL offer an editable query prefilled once from the saved title using the metadata-locale fallback. It SHALL NOT overwrite a user-edited query on late context loading, refetch or locale change, or search automatically. A query longer than this UI's supported 500-character search bound SHALL receive actionable validation rather than silent truncation. Missing context SHALL expose safe retry and prevent search or submission until context is available. Changing the work SHALL reset its draft, selection, review and outcome state.

#### Scenario: Untouched title prefill
- **WHEN** saved context first loads and the query has not been edited
- **THEN** the title prefills the query using metadata locale, English, original title and external identity fallback, without starting search

#### Scenario: Preserve manual query
- **WHEN** a user edits the query before a context response or later refetch or locale change
- **THEN** that response does not replace the user's query

#### Scenario: Context unavailable or title too long
- **WHEN** context loading fails or the query exceeds 500 characters
- **THEN** the page explains the recoverable condition and does not send a search until the context is available and query valid

#### Scenario: Move between works
- **WHEN** the route changes to a different saved work during search, review, preflight or submission
- **THEN** the new work starts with its own context and no prior draft, selection or feedback; an abandoned preflight cannot initiate a POST, and a late response cannot alter the new work

### Requirement: Comparable release results
Each release SHALL show its title and separately labeled indexer, size and seeders, including explicit localized unknown values. Zero seeders SHALL be distinct from unknown. Indexer identifiers SHALL remain an optional advanced filter, with an accessible disclosure that preserves its value when collapsed and reveals invalid input. The page SHALL retain explicit release selection, readable wrapping and keyboard access at narrow and wide widths.

#### Scenario: Compare incomplete results
- **WHEN** results include long titles, missing metrics and zero seeders
- **THEN** users can distinguish each labeled fact and explicitly select a result without horizontal page overflow at 360 pixels

#### Scenario: Collapse and correct indexer filters
- **WHEN** a user collapses populated advanced filters or submits an invalid hidden identifier
- **THEN** valid values remain effective and invalid values are revealed with associated corrective feedback

### Requirement: Reviewed acquisition intent
Before an Acquisition POST, the UI SHALL present the selected work, release and destination for explicit review and confirmation. Cancelling review SHALL send no POST. Confirmation SHALL freeze one intent and idempotency key, refresh live destinations, and allow at most one preflight or submission at a time. A disappeared destination SHALL return the user to an explicit current selection without submitting a replacement destination automatically.

#### Scenario: Review and cancel
- **WHEN** the user opens review and cancels it by its control or Escape
- **THEN** the selected work, release and destination have been visible, no POST occurs and focus returns to the review trigger

#### Scenario: Confirm once while busy
- **WHEN** the user confirms repeatedly while live destination validation or submission is pending
- **THEN** only one frozen intent is admitted and editable selection cannot change its payload

#### Scenario: Reviewed destination disappears
- **WHEN** the reviewed destination is absent from the fresh live response
- **THEN** no Acquisition POST occurs and the user must explicitly select and review an available destination

### Requirement: Explicit acquisition request recovery
An uncertain request failure SHALL retain the same frozen payload and idempotency key for explicitly labeled retry, rather than creating a new attempt. While that request is unresolved, the page SHALL NOT offer a fresh search or changed submission as if no side effect occurred. A known expired selection SHALL require fresh search. A returned failed Acquisition SHALL require fresh search and a new key for another attempt. A returned pending Acquisition SHALL be explained as uncertain, not automatically resubmitted or described as download progress. Leaving the page SHALL NOT claim to cancel a server-accepted request; local request recovery is not durable across navigation or reload.

#### Scenario: Retry an uncertain request
- **WHEN** a network, server or unclassified request failure leaves acceptance uncertain and the user chooses request retry
- **THEN** the exact same payload and key are sent without a new destination preflight or automatic new attempt

#### Scenario: Returned failure differs from a thrown request
- **WHEN** the server returns a failed Acquisition rather than throwing a transport failure
- **THEN** the page shows its safe outcome and requires fresh release search before a new keyed attempt

#### Scenario: Expired selection is actionable
- **WHEN** the server definitively returns selection_expired
- **THEN** the old selection is no longer actionable and the page guides a fresh search without replaying it

### Requirement: Clear latest acquisition outcome
Submission feedback SHALL identify the release and destination with a short localized pending, submitted or failed status and separate explanatory text. Submitted SHALL mean handed off to the download client, not downloaded. The media detail page SHALL show only the latest Acquisition status from its existing detail response, with no progress, history or reconciliation controls introduced by this change. Successful responses SHALL refresh the affected work's detail data even if the originating page has been left.

#### Scenario: Explain pending separately
- **WHEN** an Acquisition is pending
- **THEN** a short status label and separate uncertainty explanation are shown without automatic resubmission or progress claims

#### Scenario: Refresh latest detail outcome
- **WHEN** a submission response returns for a saved work and the user views its detail
- **THEN** refreshed data shows its latest Acquisition status, release and destination without rendering an acquisition history

#### Scenario: Localized accessible release workflow
- **WHEN** users perform search, review, cancellation, request recovery and outcome inspection in English or Russian at 360 and 1280 pixels
- **THEN** labels, unknown values, explanations, visible focus and announced feedback remain usable, review focus is contained and restored, and long content wraps without horizontal page overflow
