# Progress — PHASE_10_PLUS_SPEC.md addendum

Tracks Phases 10–14 only. Phases 0–9 (the original `PROJECT_BUILD_SPEC.md`) are complete —
see `SUMMARY.md` for that history. Per the addendum's own rule: update this file and the
table below at the end of every phase, so a lost session costs one file read.

## Phase status

| Phase | Feature(s) | Status |
|---|---|---|
| 10 | F54 — compliance check (A8/A9/A10) + instrumentation | **Done** |
| 11 | F52 (phonetic spell-out), F53 (confidence-flagged readback) | **Done** |
| 12 | F59 (recipient-before-compose reorder) | **Done** |
| 13 | F55/F56/F58/F57 (search, draft recovery, sign-off, attachment read-aloud) | **Done** |
| 14 | F51 (spoken PIN) — optional | **Done** |

## Phase 10 detail

**§10.1 compliance check:**
- A10 (no `alert`/`confirm`/`prompt`): clean, zero matches.
- A9 (no colour-only signalling): passes — mic-button state is also carried by `#status`
  text and distinct audio cues.
- A8 (`prefers-reduced-motion`): one violation found and fixed — `frontend/styles.css`'s
  `#mic-btn` hover/state-colour `transition` wasn't gated; moved inside the existing
  `@media (prefers-reduced-motion: no-preference)` block. Regression-tested in
  `tests/test_a8_reduced_motion.py`.

**F54 instrumentation:**
- New `events` table (`backend/data/store.py`), `backend/events.py` (`log_event()`,
  `classify_repair_turn()`, `categorize_error()`, session contextvar for `ai/provider.py`'s
  single LLM call site).
- Every event in the §10.2 table is wired from `backend/routes/voice.py`/
  `backend/ai/provider.py` — see that module's docstrings for exact call sites.
- `Settings.log_content` (`LOG_CONTENT`, default `0`) gates the only path real content can
  reach the table through (`log_event(..., content=...)`); proven end-to-end in
  `tests/test_privacy.py`.
- `GET /api/metrics/summary` and `GET /api/metrics/export.csv`
  (`backend/routes/metrics.py`), registered in `backend/main.py`.
- Frontend: `frontend/speech.js` captures whether the final transcript differed from the
  last interim result shown before it (§11.1 heuristic 1, needed as instrumentation now and
  as a Phase 11 uncertainty signal later), threaded through `app.js`/`api.js` as
  `TurnRequest.had_interim_change`.
- Nothing user-facing changed — no new spoken text, cue, or UI element; verified by running
  the full existing test suite unchanged plus the new Phase 10 tests
  (`tests/test_events.py`, `tests/test_repair_turn.py`, `tests/test_privacy.py`,
  `tests/test_metrics.py`, `tests/test_a8_reduced_motion.py`, and additions to
  `tests/test_provider.py`/`tests/test_turn_flow.py`).

## Phase 11 detail

**§11.1 confidence-signal finding:** checked directly against a real microphone via the
throwaway `dev_tools/confidence_probe.html` probe (10 utterances, the 10th deliberately
mumbled). Result: `SpeechRecognitionAlternative.confidence` is **unusable** as a per-word
uncertainty signal —
- interim results always report one of exactly two fixed constants (0.01 or 0.9) regardless
  of content;
- final-result confidence is reported once per whole utterance, never per word;
- across the 10 utterances it clustered tightly (0.76–0.89) and didn't move at all on an
  utterance that visibly self-corrected mid-recognition (`"mom ton"` → `"Mom" "tonight"`).

**Decision:** built the §11.1 fallback heuristics (word changed between interim/final;
recipient-hint word not a known contact name; address/number/date fragment; command-word
homophone) as the primary signal, per the plan's own decision rule. Confidence is not used
anywhere.

**F52 (phonetic spell-out):**
- `backend/speechify.py::spell_phonetically()` — NATO alphabet, digits as digits,
  punctuation named.
- Voice commands "spell that" / "spell the recipient" / "spell the subject"
  (`backend/commands.py`, wired in `routes/voice.py::_handle_command()`).
  `ConversationState.last_field_named` tracks which field "spell that" defaults to.
- Automatic trigger: `backend/data/contacts.py::is_known_contact()` — an unfamiliar
  recipient is spelled automatically whenever `ENHANCED_READBACK=1`.

**F53 (confidence-flagged readback):**
- `Settings.enhanced_readback` (`ENHANCED_READBACK`, default `0`) — mandatory A/B toggle.
- `backend/uncertainty.py::collect_uncertain_words()` combines the four heuristics;
  computed once, inside `_compose_and_readback()`, from that turn's own transcript and
  `TurnRequest.last_interim_transcript` (new, additive alongside Phase 10's
  `had_interim_change` boolean).
- `backend/speechify.py::build_enhanced_readback()` — a completely separate function from
  `build_readback()`, never a branch inside it, so `ENHANCED_READBACK=0` is byte-identical
  to Phase 0–10 behavior by construction, not by careful bookkeeping. Verified: the 14
  pre-existing `test_speechify.py` tests pass unmodified, plus new exact-full-string
  (not substring) regression tests, plus a route-level test that reruns the full scripted
  conversation under both flag values and asserts identical `speech` text.
  `TurnResponse.speech_segments` (new, `None` when the flag is off) carries the
  per-word rate/cue data for the flag-on case.
- Frontend: `frontend/tts.js::speakSegments()` + `frontend/cues.js::playUncertainMarker()`
  play the enhanced readback segment by segment, dropping rate and firing a distinct tone
  before each uncertain/spelled word; `app.js` only takes this path when
  `response.speech_segments` is present.
- `GET /api/metrics/summary`'s `readbacks_by_condition` ({"plain": n, "enhanced": n}) lets
  sessions be split by condition after a study, per `readback_start.detail.enhanced`.
- Nothing changes when `ENHANCED_READBACK=0` (the default) — verified by the full existing
  suite (376 tests, zero regressions) plus the byte-identical regression tests above.

**Still needs a human with a microphone** (same constraint as §11.1): dictating a real
email containing an unfamiliar address and a deliberately mumbled word under
`ENHANCED_READBACK=1`, to confirm by ear that the address is spelled and the mumbled word
is marked. Not something `pytest` can prove.

## Phase 12 detail

**F59 (recipient-before-compose reorder):**
- `backend/ai/compose.py::extract_recipient_hint()` — the same trigger-word/`_split_hint`
  heuristic `_fake_compose()` already used internally, exposed standalone so
  `routes/voice.py` can try resolving a recipient BEFORE composing, with zero model call.
- `_compose_and_readback()` gets a new pre-block: if a hint is found and resolves
  ("resolved" or "clarifying"), the ordering changes; "unknown"/"empty"/no-hint-at-all fall
  straight through to the original, byte-for-byte-unchanged compose-first code.
- **Resolved**: the recipient's learned tone (`get_tone_for_recipient`) is now looked up
  and passed into `compose_email(..., tone_hint=...)` — threaded into the actual prompt for
  real AI (`_real_compose`, mirroring `compose_reply`'s existing pattern exactly) and onto
  `Draft.tone` directly for fake AI — instead of only being patched onto the field after
  the fact. `_apply_tone_default` still runs afterward too, as a harmless safety net.
- **Clarifying**: the disambiguating question is now asked BEFORE any compose call, not
  after. `ConversationState.pending_recipient_transcript` (new) tracks this pre-compose
  shape so the clarifying-answer resolution branch knows to compose only once the name is
  actually resolved, with the now-known tone.
- **Proof, not just an assertion**: `tests/test_recipient_before_compose.py`'s
  `test_ambiguous_name_asks_before_any_compose_llm_call` runs under real `FAKE_AI=0` with
  a mocked Ollama client holding exactly one queued response (the pre-existing
  `contacts_nlp.py` ContactChoice resolution call, unrelated to this phase) — if
  `compose_email()` were ever called before clarifying, the mock's queue would be empty and
  raise loudly, not silently. The events table is also checked directly: the only
  `llm_call` logged has `fn == "ContactChoice"`, never `"DraftFields"`.
- `compose_reply()`, `_fake_compose_reply()`, `_real_compose_reply()`, and everything under
  `reading_inbox`/`review` are untouched — the reply path already had this fixed.
- Full suite: 389 tests, zero regressions (376 existing + 13 new).

## F-table addition

| ID | Feature | Phase |
|---|---|---|
| F54 | Instrumentation and evaluation harness (`events` table, `log_event`, `classify_repair_turn`, `/api/metrics/*`) | 10 |
| F52 | Phonetic spell-out of high-risk fields (`spell_phonetically`, spell commands, automatic unfamiliar-recipient trigger) | 11 |
| F53 | Confidence-flagged readback behind `ENHANCED_READBACK` (`build_enhanced_readback`, uncertainty heuristics, `speech_segments`) | 11 |
| F59 | Recipient-before-compose reorder (`extract_recipient_hint`, pre-compose tone lookup, pre-compose disambiguation) | 12 |
| F55 | Voice inbox search (`SearchQueryFields`, `ai/search_query.py`, `gmail/inbox.py::search`) | 13 |
| F56 | Draft recovery after a crash/reload (`recoverable_draft` table, `GET /api/draft/recoverable`, `resume`/`discard`) | 13 |
| F58 | "Use my usual sign-off" (`signoff_phrases` table, `record_signoff_phrase`/`top_signoff_phrase`) | 13 |
| F57 | Attachment read-aloud (`attachment_reader.py`, `pypdf`/`python-docx`, summary-first over 300 words) | 13 |

## Phase 13 detail

Built in the requested order — F55 → F56 → F58 → F57 — each landing with the full suite
green before moving to the next, so stopping early at any point would have left a
complete, working build.

**F55 (voice inbox search):** `backend/ai/search_query.py::parse_search_query()`
(fake/real dispatch, same pattern as every other `ai/` module) extracts
`{sender, subject_terms, after, before}` as plain fields only — never a raw query string;
`backend/gmail/inbox.py::_build_search_query()` is the one place that actually assembles
the Gmail `q=` string deterministically from them. New `match_search_trigger()` in
`commands.py` (mirrors `match_cc_trigger`). Results enter `reading_inbox` unchanged, so
navigation/summarise/reply/archive all keep working on them for free.

**F56 (draft recovery):** confirmed understanding of the "no session id" design before
building it — single-user app, one honest "most recent unsent draft" answer, no fragile
client-side id to keep in sync. `backend/data/draft_recovery.py` — a single-row
`recoverable_draft` table, no `session_id` column. Persisted from inside `_respond()`
whenever a real draft exists (read as the actual "every mutation" requirement, not
literally only the undo-stack push points — the gate's own "kill mid-dictation" scenario
needs the very first compose covered too). Cleared on send, save-as-draft, schedule,
cancel (="discard"), and restart — found two more real clear points (save-as-draft,
schedule) beyond the three named in the spec, since a scheduled or already-saved draft
isn't "unsent" either. `GET /api/draft/recoverable` + a new `"resume"` command; staleness
past the 12-hour window deletes the row on the spot, same real-delete privacy guarantee as
an explicit discard.

**F58 ("use my usual sign-off"):** found a real gap while planning — the existing
`phrases` table (F44) mixes openers and signoffs together as generic bookkeeping, so
pulling "the most-used signoff" out of it risked returning an opener instead. Added a
separate `signoff_phrases` table rather than overload the existing one.
`record_signoff_phrase()` reuses the exact existing `_extract_signoff()` heuristic (last
non-blank line, ≤60 chars) — not a new, stricter valediction detector. The command pushes
undo history and speaks only the last two lines (`read_last_lines()`), not a full readback.

**F57 (attachment read-aloud, built last):** added `pypdf`/`python-docx` (+ `lxml`,
`python-docx`'s own dependency) to `requirements.txt`, both free. New
`backend/attachment_reader.py::extract_text()` dispatches on extension; unsupported types
(spreadsheet, presentation, image, archive, or a generic fallback) raise a `SpokenError`
naming the type rather than failing generically. Over 300 words, `ai/summarize.py`'s
existing summarizer runs first, with the full text offered on "read it in full" —
`ConversationState.pending_attachment_text` tracks that pending offer, checked first by
`READ_FULL`'s existing handler before falling through to its original inbox-message
meaning.

**Tests:** 47 new (436 total, zero regressions) — real PDF/`.docx` fixtures generated on
the fly in the test (a minimal valid PDF built with correct byte offsets, not a checked-in
binary), the 12-hour recovery boundary on both sides, the signoff table's use-count
ranking, and route-level coverage for every new command.

## Phase 14 detail (optional — F51 spoken PIN)

Off entirely unless `SEND_PIN` is set — zero behavior change for anyone who hasn't
configured it, same pattern as `LOG_CONTENT`/`ENHANCED_READBACK`.

- `backend/sensitive_content.py::contains_sensitive_markers()` — deterministic: the
  keywords "password"/"OTP", or a loosely-formatted run of 7+ digits (covers both a bare
  account number and a card-like number with spaces/hyphens). Checked against the draft's
  subject+body at SEND time, before the real `send_email()` call.
- New `Phase` value `"awaiting_pin"`; `parse_spoken_pin()` accepts literal digits, spoken
  digit words ("one two three four"), or a mix — never guesses at a wrong-length attempt.
  A malformed answer re-asks without burning one of the 3 attempts; a valid-but-wrong one
  does.
- Three wrong attempts refuses the send and says so plainly, but **keeps the draft** —
  the user can double-check the PIN and try "send" again, or edit/cancel normally.
  `_perform_send()` is the actual send logic, extracted once and shared by both the
  no-PIN-needed path and the correct-PIN path, so neither can drift from the other.
- `awaiting_pin` added to the existing mid-draft guard (blocks reading the inbox/searching
  away from a pending PIN prompt, same as every other in-progress-draft phase).
- **README honesty requirement**: added an explicit "Known limitations" entry and a
  `.env.example`/config-table note stating plainly that a spoken PIN is a speed bump, not
  authentication — audible to anyone in the room, which is exactly the threat model it
  would appear to address. Also fixed a stale README sentence left over from Phase 9
  that still claimed the spoken PIN wasn't built.
- While touching the config table, also documented `LOG_CONTENT`/`ENHANCED_READBACK`
  (Phases 10/11), which had never been added there.
- 19 new tests (455 total, zero regressions): marker/PIN-parsing unit tests, and
  route-level coverage for disabled-by-default, non-sensitive-never-prompts, correct-PIN,
  three-wrong-attempts, a garbled non-attempt not burning a try, cancel-during-PIN, and
  the mid-draft guard.

## F-table addition (cont'd)

| ID | Feature | Phase |
|---|---|---|
| F51 | Spoken PIN before sending sensitive content, optional (`sensitive_content.py`, `awaiting_pin` phase) | 14 |

## Next up

All of Phases 10–14 are now done. Nothing left on `PHASE_10_PLUS_SPEC.md`'s roadmap.
