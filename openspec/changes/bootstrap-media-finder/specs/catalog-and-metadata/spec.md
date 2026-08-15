## Purpose

Define a durable, multilingual media catalog whose provider identities and immutable metadata revisions remain explicit and user-controlled.

## ADDED Requirements

### Requirement: Collection catalog
The system SHALL let a user create arbitrary collections, place each non-archived media item in exactly one collection or `Uncategorized`, move an item between collections, and archive rather than hard-delete items and collections.

#### Scenario: Add an uncategorized item
- **WHEN** a user adds a media item without choosing a collection
- **THEN** the item appears in `Uncategorized`

#### Scenario: Archive an item
- **WHEN** a user archives a media item
- **THEN** the item leaves active collection views, appears in Archive, and retains its revisions and acquisition history

### Requirement: Provider-scoped media identity
The system SHALL identify a movie or series by the pair `provider_key` and `external_id`.

#### Scenario: Exact identity already exists
- **WHEN** a user attempts to add an existing `provider_key` and `external_id` pair
- **THEN** the system opens or returns the existing media item instead of creating a duplicate

#### Scenario: Similar item from another provider
- **WHEN** another provider returns the same normalized title and year with a different provider identity
- **THEN** the system warns about the similarity but permits a separate item

### Requirement: Manual identity allocation and preservation
For a newly created Manual item, core SHALL allocate a UUIDv4 external identifier exactly once under `provider_key=manual`. The Manual `external_id` SHALL be immutable across edits, metadata revisions, collection moves, archive/restore, and episode CSV imports. The complete version-1 Manual JSON import schema SHALL define an optional `external_id` UUIDv4 field.

A complete version-1 Manual JSON import SHALL preserve a valid supplied Manual UUIDv4. When the import omits the identifier, core SHALL allocate a new UUIDv4. An invalid supplied identifier SHALL reject the entire import atomically. When `manual + external_id` already exists, the system SHALL target and open that existing item rather than create a duplicate; applying imported metadata to it SHALL require explicit confirmation and SHALL create a new immutable revision.

#### Scenario: Create a Manual item
- **WHEN** a user creates a Manual movie or series without importing an identity
- **THEN** core assigns one UUIDv4 external identifier and every subsequent revision preserves it

#### Scenario: Import a portable Manual identity
- **WHEN** a version-1 Manual JSON document contains a valid external UUIDv4 not present in the catalog
- **THEN** the new item preserves that UUIDv4 as its immutable Manual external identifier

#### Scenario: Import without a Manual identity
- **WHEN** a valid version-1 Manual JSON document omits `external_id`
- **THEN** core allocates a new UUIDv4 and completes the import atomically

#### Scenario: Import an invalid Manual identity
- **WHEN** a version-1 Manual JSON document supplies a malformed or non-UUIDv4 external identifier
- **THEN** the entire import is rejected and no item or revision is created

#### Scenario: Import an existing Manual identity
- **WHEN** a version-1 Manual JSON document supplies an external UUID already paired with `provider_key=manual`
- **THEN** the system opens the existing item, creates no duplicate, and applies no imported metadata until the user explicitly confirms a new revision

#### Scenario: Import episodes into a Manual item
- **WHEN** a valid atomic CSV episode import creates a new revision
- **THEN** the item's Manual external identifier remains unchanged

### Requirement: Immutable metadata revisions
The system SHALL store provider locale, provenance, provider payload, normalized metadata, user overrides, and the effective snapshot in an immutable revision envelope. Updating metadata or overrides SHALL create a new revision without modifying prior revisions.

#### Scenario: Override current metadata
- **WHEN** a user changes an effective metadata field
- **THEN** a new revision records the override and the previous revision remains unchanged

#### Scenario: Acquisition pins metadata
- **WHEN** an acquisition is created
- **THEN** it references one exact metadata revision even if the media item later receives another revision

### Requirement: Rich normalized metadata
The normalized schema SHALL be versioned and SHALL represent movies and series, including seasons, regular episodes, Season 00 specials, provider identifiers, localized titles, plot, dates, runtime, ratings, genres, tags, countries, studios, people, artwork, provenance, completeness, and structural quality.

#### Scenario: Normalize a series special
- **WHEN** a provider returns an episode in season zero
- **THEN** normalized metadata retains it as a special with its provider identity and ordering information

### Requirement: Manual metadata provider
The Manual provider SHALL support creating and editing movies and series, seasons, episodes, and Season 00 specials through the UI; importing the complete version-1 JSON schema; and atomically importing episodes from CSV. Manual revisions SHALL never expire.

#### Scenario: Valid CSV episode import
- **WHEN** every row in a CSV episode import is valid
- **THEN** the system creates one new revision containing all imported episodes

#### Scenario: Invalid CSV episode import
- **WHEN** any row in a CSV episode import is invalid
- **THEN** the system rejects the entire import and creates no partial revision

#### Scenario: Manual revision ages
- **WHEN** a Manual revision remains unchanged for any duration
- **THEN** its metadata remains exportable without a provider-expiry error

### Requirement: TMDB metadata provider
The TMDB provider SHALL search and fetch movies and series in a requested metadata locale, fetch every advertised TV season including Season 00, preserve provider provenance, normalize real TMDB episode payloads and artwork URLs, and expose required attribution for About/Credits. Its authenticated transport SHALL accept only validated TMDB endpoint shapes and SHALL reject endpoint components that could redirect or disclose its bearer token.

#### Scenario: Search TMDB in a locale
- **WHEN** a user searches TMDB with a supported metadata locale
- **THEN** results are returned separately as TMDB identities in that locale and are not merged with other providers

#### Scenario: Display attribution
- **WHEN** the About/Credits view is rendered with TMDB configured
- **THEN** it displays the official TMDB attribution and notice supplied by the module

#### Scenario: Fetch a TV hierarchy
- **WHEN** TMDB advertises regular seasons and Season 00 for a series
- **THEN** the provider fetches each season detail and normalizes its real episode hierarchy and available poster and backdrop artwork

### Requirement: Independent interface locales
The system SHALL offer English and Russian UI localization, choose the browser locale with English fallback, permit a cookie-based UI locale override, and choose metadata locale independently while defaulting it to the current UI locale.

#### Scenario: Unsupported browser locale
- **WHEN** the browser requests a UI locale that has no catalog
- **THEN** the system renders English UI text

#### Scenario: Metadata locale override
- **WHEN** a Russian-UI user selects English metadata
- **THEN** provider searches and revisions use English metadata while the interface remains Russian
