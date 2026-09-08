## ADDED Requirements

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
