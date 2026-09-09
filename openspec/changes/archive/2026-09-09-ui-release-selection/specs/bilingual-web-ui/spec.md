## ADDED Requirements

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
