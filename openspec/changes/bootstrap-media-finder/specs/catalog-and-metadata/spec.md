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
The TMDB provider SHALL search and fetch movies and series in a requested metadata locale, preserve provider provenance, and expose required attribution for About/Credits.

#### Scenario: Search TMDB in a locale
- **WHEN** a user searches TMDB with a supported metadata locale
- **THEN** results are returned separately as TMDB identities in that locale and are not merged with other providers

#### Scenario: Display attribution
- **WHEN** the About/Credits view is rendered with TMDB configured
- **THEN** it displays the official TMDB attribution and notice supplied by the module

### Requirement: Independent interface locales
The system SHALL offer English and Russian UI localization, choose the browser locale with English fallback, permit a cookie-based UI locale override, and choose metadata locale independently while defaulting it to the current UI locale.

#### Scenario: Unsupported browser locale
- **WHEN** the browser requests a UI locale that has no catalog
- **THEN** the system renders English UI text

#### Scenario: Metadata locale override
- **WHEN** a Russian-UI user selects English metadata
- **THEN** provider searches and revisions use English metadata while the interface remains Russian
