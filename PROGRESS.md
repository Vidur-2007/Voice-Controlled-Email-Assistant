# Progress — PHASE_10_PLUS_SPEC.md addendum

Tracks Phases 10–14 only. Phases 0–9 (the original `PROJECT_BUILD_SPEC.md`) are complete —
see `SUMMARY.md` for that history. Per the addendum's own rule: update this file and the
table below at the end of every phase, so a lost session costs one file read.

## Phase status

| Phase | Feature(s) | Status |
|---|---|---|
| 10 | F54 — compliance check (A8/A9/A10) + instrumentation | **Done** |
| 11 | F52 (phonetic spell-out), F53 (confidence-flagged readback) | **Done** |
| 12 | F59 (recipient-before-compose reorder) | Not started |
| 13 | F55/F56/F57/F58 (search, draft recovery, attachment read-aloud, sign-off) | Not started |
| 14 | F51 (spoken PIN) — optional | Not started |

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

## F-table addition

| ID | Feature | Phase |
|---|---|---|
| F54 | Instrumentation and evaluation harness (`events` table, `log_event`, `classify_repair_turn`, `/api/metrics/*`) | 10 |
| F52 | Phonetic spell-out of high-risk fields (`spell_phonetically`, spell commands, automatic unfamiliar-recipient trigger) | 11 |
| F53 | Confidence-flagged readback behind `ENHANCED_READBACK` (`build_enhanced_readback`, uncertainty heuristics, `speech_segments`) | 11 |

## Next up

Phase 12 (F59, recipient-before-compose reorder) — see `PHASE_10_PLUS_SPEC.md` §12.
