## Context

See `proposal.md` for motivation and the sibling `specs/bilingual-web-ui/spec.md` for behavior. This design is included because several draft/confirmation/file-read transitions need decisions before coding. The approved pre-spec handoff maps RQ-001 through RQ-007 and TC-001 through TC-007 to existing owners; its source tree is identical to main `3e47f352f0830b0bd5fd9f00f6a52a35b5d2ab47`.

`ManualAddPage` already owns structured and JSON state above its mode switch. `ManualEditForm` owns structured and CSV state; `finish` navigates after any successful mutation. `ManualEditor` is a controlled child, and `manual-document.ts` preserves rich metadata and strips row keys for the wire. The existing React Router data router and Mantine dialogs/disclosure provide the required presentation primitives. No backend contract change is necessary.

## Goals / Non-Goals

**Goals:** one page-owned draft lifecycle, one admission boundary for Manual operations, explicit loss decisions, and behavior-driven verification of the exact proposed transitions. Keep current control request/response types and normalized-document ownership intact.

**Non-Goals:** persistent storage, autosave, cross-tab locking, mutation retry or server exactly-once guarantees, a general form/state framework, a replacement router, a client CSV parser, or a coordinated form-save-plus-CSV transaction. The current server still resolves its current saved revision when accepting CSV; this UI does not add optimistic-concurrency preconditions. Existing metadata module retention, Manual revision ownership, acquisition and secret boundaries are unchanged.

## Decisions

### 1. Keep draft ownership in the current pages

Extend the page-owned editor state with four raw list strings and their initial representations. `ManualEditor` receives controlled strings and callbacks so mode/disclosure unmounting cannot lose them. Keep `ManualEditorDocument` as the normalized source for unexposed fields; use `manual-document.ts` for small projection/comparison functions.

At request construction, copy the complete document, normalize only list strings that differ from their initial representation, and then strip row keys. An unedited array is preserved byte-for-byte in JSON value terms even if an element contains a comma; editing that field intentionally opts into the existing split/trim/filter grammar. Normalization never feeds back into displayed raw strings on blur or submission failure. Tests cover restoring a string to its original value, empty strings and rich arrays, not just parser output.

Dirty comparison uses the initial page snapshot versus a stable wire-shaped document projection plus the four raw strings and applicable source/collection values. Row keys, disclosure state, operation status and UI locale are excluded. Reverting all values to the initial state is clean. Collection selection is shared by structured and JSON create: it counts for page departure but not as an unrelated structured draft when JSON will submit that same selection.

On edit, key the form lifecycle by item identity; initial state comes from that item's loaded metadata, not from a previous item. Background invalidation/UI-language changes do not reset an in-progress draft. No query cache owns unsaved fields. A small Manual-specific helper/hook is allowed only to share the same guard between the two existing pages; no app-wide abstraction or extra owner is introduced.

Alternative rejected: component-local raw strings would disappear across the add mode switch. Normalizing every array on every save would damage unedited imported comma-containing values. A persistent draft store adds a lifecycle and privacy obligation outside scope.

### 2. Use a synchronous operation gate and immutable snapshot

Keep a ref-backed admission guard with renderable page status; do not rely on `isPending` becoming visible before the next event. The current `useMutation` calls remain the writers. Guard scope covers structured and JSON create, edit, CSV, duplicate confirmation and accepted file reads on the same page.

| State | Allowed user actions | Transition |
| --- | --- | --- |
| Idle | Edit, switch modes, start one operation, navigate with dirty guard | Read, review-discard, submit or leave |
| Reading file | Replace/clear selection, edit source or switch mode to supersede the read; no mutation | Current result/error returns idle; invalidation supersedes old result |
| Reviewing alternate-draft discard | Cancel or accept captured consequences; no underlying edits | Cancel keeps both drafts; accept submits snapshot |
| Submitting / confirming / finishing | No conflicting edit, file read, mode switch, mutation, dialog dismissal or in-app departure | Error returns idle; success navigates; confirmation-required enters review |
| Reviewing duplicate confirmation | Confirm once or cancel; underlying draft frozen | Confirm submits captured token; cancel retains drafts and clears snapshot/consent |

Capture payload, item ID, relevant locale, collection and discard consent before the network action. Bind success/error callbacks to the originating mounted page instance. Keep the gate through cache invalidation/finish, so a second request cannot enter after the network response but before navigation. A failed queued navigation attempt is reset to stay; no delayed navigation occurs automatically after failure. Successful intended navigation uses a one-use bypass for that result destination only.

Duplicate confirmation owns the captured token and submitted snapshot, not whatever values might otherwise be edited behind its modal. While awaiting the user's choice, closing/cancelling the modal drops the token and consent, retains both drafts and restores focus. During the confirmation request, close/escape/overlay/cancel are disabled. A token-expired response retains drafts but requires a fresh original operation and fresh discard consent. No automatic retry is added. On page abandonment, invalidate read/snapshot callbacks; this is not a promise to undo a server mutation.

Alternative rejected: disabling only the clicked button leaves Enter and other mutation paths open. Independent pending flags are not one admission boundary. A state-machine dependency is unnecessary for this bounded table.

### 3. Make both local file loaders supersedable

The JSON and CSV `FileInput` handlers use a per-page read generation tied to source edits, selection, mode and mounted identity. Check the existing size limit before reading a known oversized file; retain submission-time byte validation for pasted text. A selected current file marks the page reading; mutation handlers reject admission until the read resolves or is invalidated. Replacing/clearing selection or typing invalidates the old generation and releases/supersedes that read state. Clearing the file selection does not erase text already loaded; the text remains directly editable.

Only the current generation writes source text or reports a read error. Current read failure keeps preceding source and uses a localized UI message; stale success/failure does nothing. Block selecting files during mutation, alternate-draft review and duplicate review. Full JSON schema/domain validation remains server-owned, and CSV remains opaque source text.

### 4. Treat discard choices as one-operation consent

Dirty in-app departure uses existing `useBlocker`; a Manual-scoped confirmation presents Stay first and explicit Leave. It never performs a save. Use `beforeunload` only while dirty/busy, remove it when clean, and accept browser-controlled messages/limited mobile reliability. Router-managed navigation to another item starts a fresh form keyed by item identity. No browser/OS recovery claim is made; [React Router](https://reactrouter.com/api/hooks/useBlocker) and [MDN](https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeunload_event) document the distinct navigation boundaries.

Before a selected operation that will navigate away, detect any other dirty draft:

| Requested operation | Unrelated draft needing explicit consent |
| --- | --- |
| Structured create | Nonempty unsaved JSON text |
| JSON import | Structured field/raw-list changes; shared collection is consumed, not discarded |
| Structured edit | Nonempty unsaved CSV text |
| CSV import | Structured dirty state blocks the request instead of offering combined execution |

Show which draft would be discarded on success; Cancel retains everything and sends nothing. Continue retains the actual draft data until success and associates consent with the frozen operation. Validation error, request failure or cancellation/expiry of duplicate review expires that consent without clearing either draft. Retrying re-evaluates the current state and prompts again when necessary.

For CSV with dirty structured fields, keep the existing form save available and add a localized explicit discard-structured action. Its confirmation restores the original saved-form snapshot and raw strings but preserves CSV. Saving first follows the normal save/confirmation/result route; it never runs CSV automatically. If that save would leave CSV behind, the alternate-draft review applies. This deliberately offers separate safe operations rather than inventing a combined transaction or silently staging a second write.

### 5. Keep destructive targets stable and dialogs accessible

`ManualEditor` captures a removal intent by stable row key and affected child count. It does not filter rows until confirmation. For populated new series-to-movie transitions, capture the desired kind but retain the current kind/hierarchy until confirmed. Lock ordinary controls while the dialog is active; cancellation/escape changes no draft and restores the initiating control. After confirmed deletion, focus the enclosing add-episode/add-season control; after kind confirmation focus the kind selector. Existing-item kind remains read-only.

Use the same installed dialog primitive, not browser confirm dialogs, for localized destructive and dirty transitions. Safe actions receive initial focus. No undo stack is needed because mutation is deferred until an explicit choice. Do not store row keys, tokens or consent in URLs/browser storage.

### 6. Limit presentation work to a small disclosure

Keep kind, active title, year, plot and allowed collection selection visible. Group original title, release date, runtime and the four lists into one secondary-field disclosure, initially closed; unedited identity stays available read-only. Keep season/episode editing as existing fieldsets and add counts derived from current draft structure, including Season 00. The disclosure does not reset any field, selection or validation state. No individual season accordion or read-only hierarchy is added.

Localize labels, pending/read failures, target/count descriptions, discard consequences and CSV guidance in both catalogs. Actions wrap and remain usable at 360px; do not change the global theme. Source/error values remain safe text, and backend error codes remain unchanged. Use existing report attachments for Manual screenshots, retaining the existing recovery capture matrix and seven CI contexts.

### 7. Verification and delegation

| Approved context mapping | Implementation seam | Proof |
| --- | --- | --- |
| RQ-001 / TC-001 | Page raw strings, editor controls, document projection | Typing/blur/mode/locale/disclosure retention; unchanged rich arrays; exact wire payload |
| RQ-002 / TC-002 | Both page operation and file handlers | Delayed rapid click/Enter, competing operations, current/stale file results, frozen token/snapshot |
| RQ-003 / TC-003 | Editor removal/kind intents | Cancel/confirm exact target, descendant counts, keyboard focus |
| RQ-004 and RQ-005 / TC-004 | Page dirty/finish/router/CSV seams | Managed navigation, other-item reset, alternate drafts, blocked dirty CSV, no chained mutation |
| RQ-006 / TC-005 | Common-field disclosure, locales, existing E2E/report | RU/EN 360x800 and 1280x800, complete labels, keyboard/focus/overflow, state preservation |
| RQ-007 / TC-006 | Existing modal assertion | Condition-based wait for visible dialog; focused test and full UI suite without product animation change |
| All / TC-007 | Existing verification and generated assets | Scoped RED/GREEN, UI gates, browser evidence, strict specs/docs, final review and delivery gates |

Terra owns page state, projection and operation coordination; Luna can implement bounded disclosure/localized presentation after the page/child interface is fixed. The primary owns shared locale integration and evidence. Avoid concurrent edits to `manual-editor.tsx` or locale catalogs; hand off file ownership explicitly. An independent reviewer checks completed behavior and scope; no new agent framework or repository harness configuration is needed.

## Risks / Trade-offs

- Lossy normalization of untouched imports -> preserve initial arrays unless that list text changed; test comma-bearing entries and rich-field round trips.
- Dialog overlap or orphaned focus -> one active page review/operation, stable intent targets, safe initial focus and explicit return destinations.
- Mobile unload is not reliable -> protect managed navigation and use best-effort unload only; do not imply autosave.
- File completion after edits -> generation checks on both success and failure, including clear, replacement and unmount.
- Single-flight is client-local -> no claim about cross-tab duplication or server write rollback; preserve existing token and revision semantics.
- Modal test failure cause/frequency is not isolated -> change only assertion waiting; preserve visibility checks and production animation, and rerun the full UI suite.
- Local browser may remain unavailable -> use the already-supported, separately authorized hosted verification path after apply; missing current screenshots remains an acceptance blocker, never a test pass.

## Migration Plan

No data migration, new API consumer or module registration is introduced. After approved implementation, rebuild packaged UI assets using the existing build command, verify the candidate, synchronize this capability delta and archive in the separately authorized phase, then use the protected PR/check/review/main/edge sequence. Reverting the UI change and generated assets restores prior interaction behavior without changing stored metadata; it also restores the known input-loss risks. Stable release is excluded. Planning completion is not permission to implement, archive or merge.
