## ADDED Requirements

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
