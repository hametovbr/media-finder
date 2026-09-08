## ADDED Requirements

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
