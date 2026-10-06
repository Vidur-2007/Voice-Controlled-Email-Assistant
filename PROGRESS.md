# Progress — PHASE_10_PLUS_SPEC.md addendum

Tracks Phases 10–14 only. Phases 0–9 (the original `PROJECT_BUILD_SPEC.md`) are complete —
see `SUMMARY.md` for that history. Per the addendum's own rule: update this file and the
table below at the end of every phase, so a lost session costs one file read.

## Phase status

| Phase | Feature(s) | Status |
|---|---|---|
| 10 | F54 — compliance check (A8/A9/A10) + instrumentation | **Done** |
| 11 | F52 (phonetic spell-out), F53 (confidence-flagged readback) | Not started |
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

## F-table addition

| ID | Feature | Phase |
|---|---|---|
| F54 | Instrumentation and evaluation harness (`events` table, `log_event`, `classify_repair_turn`, `/api/metrics/*`) | 10 |

## Next up

Phase 11 (F52/F53) — gated on a real-browser confidence check (§11.1) that only a human
with a microphone can run; see the phase-11 plan for the handoff.
