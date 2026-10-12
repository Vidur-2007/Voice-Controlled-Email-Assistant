# Project Summary 2 — Live bug fixes + the saved-drafts feature

`SUMMARY.md` covers Phases 0–9 and the completeness audit. `PROGRESS.md` covers the
`PHASE_10_PLUS_SPEC.md` addendum, Phases 10–14 (F54 instrumentation, F52/F53 spell-out and
confidence readback, F59 recipient-before-compose, F55/F56/F58/F57, F51 the optional spoken
PIN) — all of that was finished and is not repeated here.

This document picks up from there: what happened once the app was actually run with a real
browser, real Ollama, and a real Gmail account, and the one new feature built after that.

---

## 1. Four rounds of live bug fixes

Once real usage started, four separate problems were reported from actual console
transcripts (not hypothetical cases) and fixed in order. The common thread across all four:
**commands that carry free-form spoken content (a new address, reply text) had only ever
been built to accept that content on a separate follow-up turn — but people naturally say
the trigger word and the content in one breath.** Each round dug one level deeper than the
last.

### Round 1 — four separate reports in one message

1. **"Change recipient" didn't work at all.** No grammar existed for it.
2. **Spaces in a spoken address were being turned into periods.** Saying "vidur bandaru"
   showed correctly on screen as "Vidur Bandaru" but sent to `vidur.bandaru@...` — the old
   recipient-resolution fallback (`_resolve_recipient_stub`, Phase 4's permissive escape
   hatch) always slugified *any* spoken hint into a fake placeholder address; it was never
   designed to parse a real spoken email address at all.
3. **"Dictate this" sometimes leaked into the composed email** when Chrome's speech
   recognizer inserted a comma or colon right after the trigger phrase — the override
   matcher in `backend/ai/mode_detect.py` required an exact single space afterward.
4. **Plural phrasing** ("read my unread mails") fell through the grammar entirely, since
   `_PHRASES` only had the singular "read my unread mail".

**Fixes:** added `match_change_recipient()` as new grammar; wrote
`_parse_spoken_email()` in `backend/routes/voice.py` to turn "vidur bandaru at gmail dot
com" (or Chrome's own partially-formatted "...1.0@gmail.com") into a real address instead of
a placeholder, with `_resolve_recipient_stub()` now trying that first; loosened
`mode_detect.py`'s trigger-boundary check to tolerate ASR punctuation; added the plural
phrases to `_PHRASES`.

### Round 2 — "change recipient" still failing, revealing a second, different bug

The fix above worked for a bare "change recipient" followed by a second turn with the new
address — but saying it all in one breath ("change the recipent to VVS mini project
1.0@gmail.com") still failed, for an unrelated reason: **Chrome's own speech recognizer
sometimes applies mid-utterance "smart formatting,"** turning spoken "at"/"dot" into literal
`@`/`.` characters unpredictably, inconsistently between utterances.

**Fix:** `_parse_spoken_email()` was rewritten to detect a literal `@` already present in
the transcript (Chrome's smart-formatting case) and prioritise that over the spoken-word
"at"/"dot" case, since a literal `@` is unambiguous. `_resolve_address_answer()` was
factored out so this single parsing path is shared by the initial "who should this go to"
answer, the two-turn "change recipient" flow, and "change recipient to X" said as one
utterance — instead of three separate, drifting implementations.

### Round 3 — the same bug persisted because ASR had mis-heard the trigger word itself

The console showed the literal transcript "change **receipetant** to bandaru
weather@gmail.com" — Chrome had phonetically mis-heard the word "recipient" itself. No exact
or prefix string match can tolerate that.

**Fix:** `match_change_recipient()` was rewritten to match *structurally* ("change
`<word(s)>` [to `<value>`]") and only require the target word(s) to be **fuzzy-close**
(`rapidfuzz.fuzz.ratio`, threshold 65) to "recipient"/"email"/"address" — catching
"receipetant", "recipiant", "recipitant", etc. without enumerating every possible
mis-hearing, while still correctly rejecting unrelated edits like "change the tone to
formal" (verified directly: "tone" scores nowhere near any of the three synonyms). This
established a general rule for the rest of the session: **any new voice command built on an
uncommon keyword needs fuzzy, ASR-tolerant matching from the start, not exact-string
matching**, since this is now the second time exact matching against a real keyword failed
in live use.

### Round 4 — replying was "not available"

```
You: reply create how are you doing
Assistant: That's not available yet.
```

"Reply"/"reply all" had only ever been grammar-matched as bare commands expecting the reply
content on a separate turn — exactly the Round-1/2 pattern again, just in the reply path
this time.

**Fix:** added `match_reply_trigger()`/`match_reply_all_trigger()` (checked in that
priority order, so "reply all ..." is never swallowed by the bare "reply " prefix). Factored
the actual reply-composition logic out into `_fill_reply_content()`, shared by the existing
two-turn "review" phase and the new one-utterance path, so neither can drift from the other.

### Result

All four rounds fixed, with the existing 376-test suite passing unchanged plus new
regression coverage (`tests/test_bugfixes.py`) for every mis-hearing variant, every ASR
punctuation shape, and an explicit test proving the *old* two-step flows still work
unchanged. None of this was committed/pushed during the session — it's sitting in the
working tree, pending your go-ahead.

---

## 2. New feature: "read my drafts" / "send my saved draft"

After the bug fixes, you asked how to send a previously-saved draft — and the honest answer
was that this capability had never existed. `SAVE_DRAFT` could *create* a real Gmail draft,
but nothing anywhere could list, browse, or send one back. This was built as new,
from-scratch functionality, following the architecture Phase 6 already established for
reading the inbox.

**What it does:**
- **"read my drafts"** (or "check my drafts") lists every saved draft, numbered, and enters
  a new `reading_drafts` phase.
- **"next draft" / "previous draft"** navigate through them, exactly like "next email" /
  "previous email" does for the inbox.
- **"send"** (the same word already used to send a composed email) is now phase-aware: said
  while browsing drafts, it sends whichever draft you're currently on — the same pattern this
  app already uses to let "repeat"/"read it in full" mean different things depending on
  where you are in the conversation.
- **"send my saved draft"** is a direct shortcut from anywhere: if you have exactly one
  saved draft, it sends it outright; if you have more than one, it asks you to say "read my
  drafts" first, rather than guessing which one you meant.

**How it's built:**
- `backend/gmail/drafts.py` (new) — `list_drafts()` / `send_draft(id)`, dispatching
  fake-vs-real exactly like every other Gmail module. Real mode calls Gmail's own
  `drafts().list()` / `.get()` / `.send()`.
- `backend/gmail/fake.py` — saved drafts now also register in a small id-keyed in-memory
  store (`_fake_drafts`), separate from the existing `outbox.jsonl` append-only log, since
  sending a draft later needs to fetch and remove it *by id* — something a flat log can't
  do.
- `backend/models.py` — new `DraftSummary` model (mirrors `InboxItem`) and a new `Phase`
  value, `"reading_drafts"`.
- `backend/session.py` — new `drafts` / `draft_browse_index` state, mirroring
  `inbox` / `inbox_index`.
- `backend/commands.py` — new grammar: `READ_DRAFTS`, `NEXT_DRAFT`, `PREV_DRAFT`,
  `SEND_DRAFT`; a new `help_speech()` entry for the `reading_drafts` phase.
- `backend/speechify.py` — `describe_draft_item()` / `build_drafts_listing()`, mirroring
  `describe_inbox_item()` / `build_inbox_listing()`.
- `backend/routes/voice.py` — the new command handlers, plus the existing `SEND` intent
  gaining one new branch for the `reading_drafts` phase.

**Tests:** `tests/test_drafts_feature.py`, 16 new tests — fake-mode save/list/send,
real-vs-fake dispatch, full navigation (next/previous, at-first/at-last), sending while
browsing (and the list shrinking correctly afterward), the single-draft direct-send
shortcut, the multiple-drafts "ambiguous, please browse first" response, the mid-compose
guard, and the phase-specific help text. Full suite: **509 passing, zero regressions**
(493 existing + 16 new).

---

## 3. Current state

Nothing from this document has been committed or pushed yet — both the four rounds of live
bug fixes and the new saved-drafts feature are sitting in the working tree, offered but not
yet confirmed for a commit.
