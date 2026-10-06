# Build Specification — Addendum: Phases 10–14

> **You are Claude Code. This extends `PROJECT_BUILD_SPEC.md`, which you must read first.**
> Everything in that document still binds — the accessibility rules A1–A14, the engineering
> rules, the contracts in §20, the offline-mode rule, and the definition of done.
> Nothing here overrides any of it.
>
> Phases 0–9 are complete. This document defines Phases 10–14.
> Build **one phase at a time**, stop at each gate, and wait for approval.

---

## Why these phases exist

The system is feature-complete against the original brief. What it lacks is **evidence
that the core design decision works**, and three capabilities that close gaps the build
itself documented.

The original spec's central justification was this finding: listeners catch only ~40% of
speech-recognition errors when reviewing by audio, and blind listeners hold no advantage
despite far greater experience with synthetic speech. That paper tested *detection only,
and explicitly did not test any remediation technique.*

Phases 10 and 11 build the remediation and the measurement to evaluate it. Phase 12 fixes
a limitation the build recorded in its own summary. Phase 13 completes half-built features.
Phase 14 is optional.

---

## New features

| ID | Feature | Phase |
|---|---|---|
| F52 | Phonetic spell-out of high-risk fields | 11 |
| F53 | Confidence-flagged readback, behind an A/B toggle | 11 |
| F54 | Instrumentation and evaluation harness | 10 |
| F55 | Voice inbox search | 13 |
| F56 | Draft recovery after a crash or reload | 13 |
| F57 | Read attachment contents aloud | 13 |
| F58 | "Use my usual sign-off" command | 13 |
| F59 | Recipient-before-compose pipeline reorder | 12 |
| F51 | Spoken PIN before sending sensitive content | 14 (optional) |

---

# PHASE 10 — Compliance check and instrumentation

## 10.1 Compliance verification (do this first, it is quick)

The build summary documents rules A1–A7 and A11–A14 but does not mention **A8, A9 or A10**.
Verify them and report:

- **A8** — is `prefers-reduced-motion` respected by every animation? Grep the CSS.
- **A9** — is any state signalled by colour alone, without a matching status string and audio cue?
- **A10** — grep for `alert(`, `confirm(`, `prompt(`. There must be zero.

Fix anything that fails, with a test where a test is possible. Report findings before moving on.

## 10.2 F54 — Instrumentation

The purpose is to make the system measurable. Nothing here is user-facing.

### Storage

Add one table. Do not change any existing table.

```sql
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  ts TEXT NOT NULL,              -- ISO 8601
  event TEXT NOT NULL,           -- see the event list below
  phase TEXT,                    -- conversation phase at the time
  ms INTEGER,                    -- elapsed time, where meaningful
  detail TEXT                    -- small JSON blob, see the privacy rule
);
```

### Privacy rule — binding

**Never log email bodies, subjects, recipient addresses, or raw transcripts by default.**
`detail` carries metadata only: word counts, confidence scores, intent names, boolean flags,
error categories. A separate flag `LOG_CONTENT=0` (default `0`) may enable full-text logging
**for a consented study session only**, and the README must say so plainly.

This is not optional. The system handles private correspondence for a population already
documented as having heightened privacy concerns about voice assistants.

### Events to log

| Event | `ms` | `detail` |
|---|---|---|
| `turn_start` | – | `{transcript_words}` |
| `asr_result` | – | `{words, min_confidence, mean_confidence, had_interim_change}` |
| `command_matched` | – | `{intent}` |
| `llm_call` | elapsed | `{fn, model, output_words, retried}` |
| `draft_created` | – | `{mode, body_words, subject_words}` |
| `edit_requested` | – | `{kind}` — tone, length, free-form, undo |
| `repair_turn` | – | `{reason}` — see below |
| `readback_start` | – | `{body_words, enhanced}` |
| `send_confirmed` | – | `{}` |
| `send_result` | elapsed | `{success, error_category}` |
| `error_spoken` | – | `{category}` |

**A "repair turn"** is any turn where the user corrects something rather than advancing:
mid-speech self-correction, undo, "start over", a contact re-disambiguation, or an edit
issued after readback has already begun. Classify these in one place so the definition
stays consistent.

### Derived metrics

Add `GET /api/metrics/summary` returning, per session and in aggregate:

- turns per completed send
- repair turns per completed send
- wall-clock seconds from first turn to `send_result`
- model latency: median and 95th percentile per function
- edits issued after readback began (a proxy for errors the readback surfaced)
- sends abandoned (cancel or start-over after a draft existed)

Add `GET /api/metrics/export.csv` producing one row per event. This is what you analyse
after a study session.

### Tests

- Every event type is emitted at least once across the existing conversation-flow tests.
- `LOG_CONTENT=0` never writes a transcript, body, subject or address into `detail`. Assert this by scanning the table after a full scripted conversation containing a distinctive string.
- The metrics endpoints return valid output on an empty database.

### Phase 10 gate

- A8/A9/A10 verified, findings reported, failures fixed.
- `pytest -q` passes, including the new privacy-scan test.
- Running the §33 demo script produces a populated `events` table, and `/api/metrics/summary` reports sensible numbers.
- Nothing user-facing changed. The demo behaves identically.

---

# PHASE 11 — Error surfacing (F52, F53)

This is the research contribution. Build it carefully.

## 11.1 Verify the confidence signal first

**Before building anything**, check whether `SpeechRecognition` actually provides usable
confidence on this browser. In Chrome, `SpeechRecognitionAlternative.confidence` is
frequently `0` for interim results and is sometimes a constant for finals.

Write a tiny throwaway page or console snippet that logs `confidence` for ten real
utterances, including a deliberately mumbled one. Report what you observe. Then choose:

- **If confidence varies meaningfully** → use it as the primary uncertainty signal.
- **If it is constant or always zero** → use the fallback heuristics below instead, and say so.

### Fallback uncertainty heuristics (use if confidence is unusable)

Rank a word as uncertain if any hold:

1. **It changed between the last interim result and the final result.** The recogniser revised it — a strong, browser-independent uncertainty signal. Capture interim transcripts and diff them against the final.
2. It is a proper noun not matching any known contact name.
3. It is part of an email address, a number, a date or a time.
4. It is a homophone of a command word ("send"/"sent", "to"/"two").

Heuristic 1 alone is worth implementing regardless of whether confidence works, because
it needs no browser cooperation.

## 11.2 F52 — Phonetic spell-out

- Voice command **"spell that"** spells the current field being discussed; **"spell the recipient"**, **"spell the subject"** address a specific field.
- **Automatic** for any recipient address that is not an existing contact — an unfamiliar address is both the most likely to be misheard and the most costly to get wrong.
- Use the NATO alphabet: *"J for Juliet, O for Oscar, H for Hotel, N for November"*. Digits are read as digits. Punctuation is named: "dot", "at", "hyphen", "underscore".
- Spelling is **slower than normal speech** — drop the rate for the spelled portion and restore it afterwards.
- Lives in `backend/speechify.py` as a pure function, so it is testable without FastAPI.

## 11.3 F53 — Confidence-flagged readback

Behind an environment flag so it can be switched off for comparison:

```
ENHANCED_READBACK=1   # 0 = plain readback, exactly as Phases 0–9 behave
```

**This toggle is mandatory.** Without it you cannot run the A/B in §11.5, and the A/B is
the entire point of the phase.

When enabled, the readback:

1. Reads the **recipient first and alone**, then pauses, then subject, then body. (Phases 0–9 may already do this; confirm it.)
2. Marks uncertain words with a short, distinct tone immediately before the word, **and** drops the speech rate for that word.
3. Ends with an explicit prompt naming the risk: *"I was unsure about two words. Say 'spell that' to hear them letter by letter, or tell me what to change."*
4. If the recipient is an unfamiliar address, spells it automatically (F52).

Never announce a count of zero. If nothing is uncertain, the readback ends as it does today.

## 11.4 Tests

- The NATO speller handles addresses, digits, hyphens, underscores and mixed case.
- `ENHANCED_READBACK=0` produces byte-identical readback strings to the current behaviour — assert this against stored fixtures from the existing tests.
- An uncertain-word marker appears exactly where the uncertainty data says it should, and nowhere else.
- The "I was unsure about N words" sentence is never emitted with N = 0.

## 11.5 Phase 11 gate

- Confidence-signal finding reported, with the chosen approach justified.
- With `ENHANCED_READBACK=0`, the full existing test suite still passes unchanged.
- With `ENHANCED_READBACK=1`, dictate an email containing an unfamiliar address and a deliberately mumbled word; confirm by ear that the address is spelled and the mumbled word is marked.
- `/api/metrics/summary` shows `enhanced` recorded on `readback_start`, so sessions can be split by condition afterwards.

---

# PHASE 12 — Recipient-before-compose (F59)

## The problem, as the build itself recorded it

> *"A fresh email's tone can only be set as a field default from past behaviour, not used
> to actually reword the body. By the time the system knows who you're emailing, the AI
> has usually already written the body."*

Learned tone (F42) is therefore inert for new messages. Replies are unaffected because the
recipient is known before anything is written.

## The fix

Reorder the idle-phase turn flow so contact resolution runs **before** composition **when a
recipient is identifiable from the transcript**:

```
idle + unmatched transcript
  ├─ extract a recipient hint cheaply (existing heuristics; no model call)
  ├─ hint found?
  │    ├─ yes → resolve contact → look up learned tone → compose WITH that tone
  │    └─ no  → compose first (current behaviour), resolve after
  └─ ambiguous contact → clarify BEFORE composing, not after
```

Resolving before composing also means a user disambiguating "which John" no longer waits
through a draft that may be discarded — which on a CPU-only machine saves 10–20 seconds
of dead time on exactly the turn that already felt slow.

## Constraints

- **Do not** add a model call to extract the hint. Use the existing deterministic patterns ("email X", "tell X", "reply to X"). If they do not fire, fall back to the current order.
- The learned tone becomes the **default**, still overridable in the same turn ("tell John I'll be late, make it formal") and afterwards.
- Replies keep their current path. Do not touch what already works.

## Phase 12 gate

- "Tell John Smith I'll be late" — if a formal tone was previously learned for that recipient, the first draft is already formal, with no second request.
- "Email John" with two Johns asks the disambiguating question **before** any draft is composed. Confirm from the metrics log that no `llm_call` occurred before `command_matched`/clarification.
- A transcript with no identifiable recipient still composes exactly as before.
- Full suite passes.

---

# PHASE 13 — Usability completions

Four independent items. Build them in this order; each can stand alone if time runs short.

## 13.1 F55 — Voice inbox search

- Command: **"find the email from Priya about the invoice"**, "search for the message about the timetable".
- Convert the spoken request into a provider search query using **one schema-constrained model call** returning `{sender: str, subject_terms: str, after: str, before: str}` — all optional, empty string where absent. Build the provider query string deterministically from those fields. Do not let the model emit raw query syntax.
- Results enter the existing `reading_inbox` phase, so navigation, summarisation and reply all work unchanged.
- Speak the count first: *"Three messages match. The first is from Priya Sharma, subject: March invoice."*
- No matches → *"I couldn't find any message matching that. Try naming just the sender."*

## 13.2 F56 — Draft recovery

Conversation state is in-memory, so a crash or accidental reload after a long dictation
loses everything.

- Persist the current draft to SQLite on **every mutation** (the same points that already push to the undo stack).
- Do **not** try to persist or restore the session id. On page load, the client asks `GET /api/draft/recoverable`; the backend returns the most recent unsent draft newer than 12 hours, if one exists. For a single-user local application this is sufficient and avoids storing an id client-side.
- Offer it in speech: *"You have an unfinished message to John Smith, about twenty words. Say 'resume' to continue, or 'discard'."*
- Clear the stored draft on send, on discard, and on "start over".
- Respect the privacy rule: this table holds real content, so it must be covered by the same gitignore as the rest of the database, and discarding must actually delete the row.

## 13.3 F58 — "Use my usual sign-off"

Phrase tracking exists as bookkeeping but no command consumes it. Complete it.

- **Capture:** when a dictated body ends with a short closing line ("Thanks, Vidur", "Best regards"), record it as a sign-off phrase with a use count.
- **Command:** "use my usual sign-off" appends the most-used one to the current draft, then re-reads the last two lines so the user hears what changed.
- Nothing is ever auto-inserted without that explicit command in that turn. This was a deliberate decision in Phase 8; keep it.
- No sign-off recorded yet → *"I haven't learned a sign-off from you yet. Dictate one at the end of a message and I'll remember it."*

## 13.4 F57 — Attachment read-aloud (lowest priority)

- Command: "read the attachment", "what's in the attachment".
- Extract text from PDF (`pypdf`) and Word (`python-docx`); pass plain text through unchanged. Both libraries are free; add them to `requirements.txt`.
- Anything else → *"That attachment is a spreadsheet, and I can't read it aloud yet."* — name the type rather than failing generically.
- Over 300 words, offer a summary first using the existing summariser, with the full text on request.
- Never speak raw markup.

## Phase 13 gate

Each item demonstrated by voice, with the monitor off:
- A search by sender and topic returns and reads results.
- Kill the browser tab mid-dictation, reload, and recover the draft.
- "Use my usual sign-off" appends a previously dictated sign-off.
- A PDF attachment is read or summarised aloud.
- Full suite passes; new tests cover the query builder, the recovery window boundary, and the text extractors.

---

# PHASE 14 — Optional: F51 spoken PIN

Only if Phases 10–13 are green and you still have time.

- A four-digit PIN set once in `.env`, requested before sending when the draft contains detected sensitive markers (account numbers, "password", "OTP", card-like digit runs).
- Three failed attempts → refuse to send and say so plainly.
- **The README must state honestly that this is a speed bump, not authentication** — a PIN spoken aloud is audible to anyone in the room, which is precisely the threat model it appears to address. Say so rather than implying security it does not provide.

---

# The evaluation (what Phases 10 and 11 are for)

Not a build task — a protocol for the developer. Claude Code should write it into
`EVALUATION.md` at the end of Phase 11.

**Participants:** 5 people who use a screen reader daily. Even 3 produces a reportable finding.

**Design:** within-subjects, counterbalanced. Each participant completes 3 send tasks with
`ENHANCED_READBACK=0` and 3 with `=1`, order alternated between participants.

**Tasks:** one dictation to a known contact, one brief-mode message to an ambiguous name,
one reply to a message in the inbox.

**Measures**, all already captured by F54:
- recognition errors present vs. errors corrected before send — the headline number
- repair turns per completed send
- time from first turn to send
- tasks completed without sighted assistance

**The question:** does recipient-first readback with spell-out and uncertainty marking
improve error detection over plain readback?

**Report the result honestly, including a null one.** "No measurable improvement, n=5" is a
legitimate finding and more useful than a claim the data does not support. Keep per-participant
data; with this sample size the individual traces matter more than the mean.

---

# Rules for this addendum

1. **Do not regress Phases 0–9.** Every existing test must keep passing, unchanged, at every gate.
2. **`FAKE_AI=1 FAKE_GMAIL=1` must still run everything end to end**, including all new features. New fakes for every new external call.
3. **Zero paid components.** `pypdf` and `python-docx` are free; nothing else gets added.
4. **Update `PROGRESS.md` and the F-table at the end of every phase**, so a lost session costs one file read.
5. **If something here conflicts with `PROJECT_BUILD_SPEC.md`, that document wins** — say so rather than improvising.
