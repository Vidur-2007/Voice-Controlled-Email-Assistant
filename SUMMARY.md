# Project Summary — Voice-Controlled Email Assistant

This document explains, in detail, what was built, why, and how — covering every phase
of the project from the initial skeleton through the final completeness audit. It's
written as a standalone record: you shouldn't need to re-read the full build
conversation to understand what exists and why it works the way it does.

`PROJECT_BUILD_SPEC.md` is the original design specification this was built against.
`README.md` is the short, practical "how to run/test this" reference. This document is
the detailed narrative of the build itself.

---

## 1. What this project is

A voice-controlled email client built specifically for blind and visually-impaired
users. Every single interaction — composing an email, editing it, sending it, reading
your inbox, replying, attaching a file, scheduling a send — is designed to be completed
entirely by voice, with audio feedback (spoken sentences and distinct tones) for every
state change. It is **not** a normal email client with voice bolted on afterward; the
whole interaction design was built audio-first, because research cited in the spec shows
that accessibility overlays bolted onto visual-first interfaces actively fight assistive
technology rather than cooperating with it.

The on-screen transcript log that exists in the browser is a convenience for sighted
developers testing the app — it is explicitly not part of the primary interface, and
the app is designed to be fully usable with the monitor off.

### Technology stack

- **Backend**: Python 3.10, FastAPI, Pydantic v2 (strict `model_dump()`/`model_validate()`
  usage — never the deprecated `.dict()`/`.parse_obj()`), stdlib `sqlite3` (no ORM),
  `rapidfuzz` for fuzzy contact-name matching.
- **AI**: a local Ollama model (`llama3.2:3b`, free, runs entirely on-device) for email
  composition/editing/summarisation, accessed through exactly one call site
  (`backend/ai/provider.py`) so swapping providers is a config change, not a rewrite. A
  Gemini fallback path exists in the code but is deliberately left unconfigured — it's
  there so a real API key could be added later without a rewrite, not because it's
  needed right now.
- **Email**: the real Gmail API (`google-api-python-client`) for sending, reading,
  replying, and scheduling mail, with OAuth handled via a one-time (or occasional
  re-) browser sign-in.
- **Frontend**: plain HTML, CSS, and vanilla JavaScript. No npm, no bundler, no build
  step, no framework. Six small, focused JS modules, each with one clear job.

### The offline-mode rule (the single most important design decision)

Two environment flags — `FAKE_AI` and `FAKE_GMAIL` — let the **entire application** run
end to end with zero credentials, zero API keys, and zero network calls. Every single
feature has a deterministic, offline "fake" implementation sitting right next to its
real one, selected by one `if settings.fake_ai:` / `if settings.fake_gmail:` check at the
top of each public function. This is why every one of the 305 automated tests can run
in under three seconds with no internet connection at all, and why the whole interaction
design could be built and refined before any real Gmail/Ollama access ever existed.

---

## 2. How the pieces fit together

### The turn orchestrator — the heart of the whole app

Every single voice interaction, no matter how complex, flows through one function:
`POST /api/turn` in `backend/routes/voice.py`. The frontend sends `{session_id,
transcript}`; the backend always returns `{speech, phase, draft, ok, ...}` — one spoken
sentence that is *never* empty, never a stack trace, never raw JSON. The order of checks
on every single turn is:

1. **Is the transcript empty?** → ask the user to repeat themselves.
2. **Mid-speech self-correction** ("no wait, change that to...") is stripped from the
   transcript *before* anything else looks at it, so a correction never leaks into what
   gets composed or edited.
3. **Does it match the deterministic command grammar** (`backend/commands.py`)? Things
   like "send," "cancel," "undo," "read the subject," "add cc Sarah" are matched by
   exact phrase or a prefix pattern — before any AI model is ever touched. This is what
   makes commands instant and 100% predictable, rather than depending on an AI's mood.
4. **Otherwise, branch on the conversation's current phase** — composing, waiting for a
   contact name to be disambiguated, waiting for a time to schedule a send, reading an
   inbox, reviewing a reply draft, and so on.

Conversation state (`backend/session.py`) lives entirely in memory, one object per
browser tab (a UUID generated client-side, held only in a JS variable — never
`localStorage`, since that's unnecessary and unavailable in some contexts). This is
deliberate: it's a single-user, local app, so there's no need for a database-backed
session store.

### Accessibility rules, baked into the architecture, not bolted on

Fourteen binding rules (A1–A14) govern everything, and they're enforced by actual code
structure, not just convention:

- **A1** — the microphone is tap-to-toggle only, never press-and-hold.
- **A2** — there is exactly *one* live region in the entire app (`#status`); nothing
  else is ever allowed to carry `aria-live`.
- **A3** — every distinct event (listening started, listening stopped, an error, a slow
  operation still working, the wake word being heard) gets its own, genuinely different
  audio tone, so a failure is identifiable by ear alone.
- **A4** — the spoken `help` command always lists only the commands usable in whatever
  phase the conversation is currently in, never a fixed list.
- **A5** — every possible failure path ends in a spoken sentence. Nothing fails silently,
  anywhere, ever.
- **A6** — reading the whole draft back before "send" is honoured is mandatory and
  enforced **server-side** — the frontend can't skip or disable it even if it wanted to.
- **A7** — every interactive control is a real `<button>`, never a styled `<div>`; focus
  outlines are never suppressed.
- **A11** — every single message the backend can ever speak is audited to be a complete,
  plain English sentence — no stack traces, no HTTP codes, no `null`, no snake_case.
- **A12** — text is normalised before being spoken: `john.smith@example.com` becomes
  "john dot smith at example dot com," markdown is stripped, paragraph breaks become
  audible pauses.
- **A13** — the app actively avoids fighting screen readers (no double-announcements).
- **A14** — anything slower than 1.5 seconds gets an audible acknowledgement within 1.5
  seconds, because on a CPU-only machine a real AI call can take 10-20 seconds, and
  silence is indistinguishable from "it's frozen" when you can't see a spinner.

---

## 3. Phase-by-phase build history

### Phase 0 — Skeleton

The bare FastAPI app, the full Pydantic data-contract file (`backend/models.py` — every
shape every other module imports from), the SQLite schema (six tables, several of which
sat unused for a long time until later phases needed them), and the offline-mode flags.
Nothing user-facing worked yet, but the whole shape of the app already existed.

### Phase 1 — Offline end to end

The first real conversation flow: compose → read back → confirm → "send" (writing to a
local `outbox.jsonl` file instead of a real inbox). "Cancel" and "start over" both work
from any point in the conversation. This is the phase where rule A5 ("never fail
silently") and A4 ("help always matches the current phase") were first proven out — the
whole app could already be demoed, fully offline, by the end of this phase.

### Phase 2 — Voice frontend

The actual voice I/O: `speech.js` (wraps the browser's `SpeechRecognition`),
`tts.js` (wraps `speechSynthesis`), `cues.js` (the WebAudio tones), `a11y.js` (the one
live region). This phase fought through several real, documented Chrome quirks:
utterances silently cut off after ~15 seconds of speech (fixed by chunking text into
≤200-character pieces and queuing them), short single-word answers sometimes never
getting marked "final" by the recognizer (fixed with a fallback timer), and the
AudioContext needing to be created inside a genuine user click or it stays silently
suspended forever.

### Phase 3 — Language processing

Real AI composition arrived here: dictation mode (your exact words, only
capitalisation/punctuation/filler-word cleanup — never rephrased), brief mode (a short
instruction expanded into a full email by the AI), automatic detection between the two,
a manual override ("dictate this" / "write it for me"), tone control ("make it more
formal"), length control ("make it shorter"), and conversational editing without
starting over, plus full undo/redo. Every AI call, in both the fake and real paths,
passes through exactly one function (`backend/ai/provider.py::generate()`), and every
single one of them uses **structured output** — the AI is constrained to a JSON Schema,
never asked for "please reply in JSON" and then hopefully parsed.

### Phase 4 — Contacts

Spoken names resolve to real email addresses: fuzzy matching (so "John" finds "John
Smith" even with imperfect pronunciation), a deterministic decision rule for when a
match is confident enough to use outright versus ambiguous enough to ask about,
relationship aliases ("my manager"), group/distribution lists ("the whole team"), and a
graceful fallback when a name genuinely isn't a known contact. Disambiguation always
offers an ordinal alongside a name ("say the last name, or say one or two") because a
blind user can't read a list off the screen.

### Phase 5 — Real email sending

Real Gmail integration: OAuth (a one-time, necessarily sighted browser sign-in — there's
no way to drive Google's consent screen through voice alone, and the app says so
honestly rather than pretending otherwise), real sending, real provider-side drafts, and
a complete mapping from every possible failure (expired token, no permission, provider
overloaded, no internet) to a spoken sentence that always states plainly whether the
email actually went out.

### Phase 6 — Reading mail

The inbox becomes real: "read my unread mail," navigating between messages, hearing who
a message is from, a short AI-generated summary, archiving, marking read, and replying
with the original thread fed into the AI so the reply is actually coherent. This phase
also had to correctly walk Gmail's MIME structure to extract readable text from a real
email — preferring plain text, falling back to HTML with the tags stripped, and never
speaking raw HTML — and get real reply-threading right (a reply only threads correctly
under the original message if the `threadId`, `In-Reply-To`, and `References` headers,
and the subject, all agree; getting just the `threadId` right, which is the easy part,
produces a reply that *looks* threaded in testing but silently isn't, in reality).

### Phase 7 — Advanced editing and actions

Mid-speech self-correction, "new paragraph" as a real formatting command inside
dictation, adding a CC by voice, attaching a file (with an honest acknowledgement that a
native OS file picker needs a real, synchronous click — voice alone genuinely cannot
open one, for the same class of reason OAuth can't be driven by voice), and scheduling a
send for later (a small, dependency-free time parser, and a background thread that polls
for due sends — deliberately not a new library dependency, since nothing like that
existed in the project yet and the amount of actual logic needed was small).

### Phase 8 — Personalisation and accessibility hardening

Three forms of a user's own past behaviour start to matter: the tone they used with a
given recipient is remembered and defaulted next time; frequent sign-offs/openers are
tracked (deliberately as bookkeeping only — nothing is ever auto-inserted into a real
outgoing email without an explicit command that turn, by your own explicit choice); and
the speech rate you set with the slider now survives a page reload, via a new small
`/api/prefs` endpoint. Then a genuine accessibility **audit**, not just new features:
eight separate spoken error messages, across three different files, were found to
describe a failure without ever stating whether the email was actually sent — a direct
violation of the project's own rule that every failure message must say so. All eight
were reworded and pinned down with dedicated tests that force every single row of the
error table.

### Phase 9 — Wake word ("hey ultron")

The one optional stretch feature chosen (a spoken PIN before sending was the other
option; the wake word was picked). Say "hey ultron" and the app starts listening,
exactly as if you'd tapped the button — or say the whole command in one breath ("hey
ultron, tell John I'll be late") and it composes directly. It's opt-in and off by
default, and turning it on speaks a full, honest disclosure first: the browser's speech
recognizer sends audio to Google's servers for processing, so "always listening" is a
genuinely different privacy posture than the normal tap-to-start model, not something to
quietly switch on. Implementing this surfaced and fixed two real bugs: tapping the mic
while the wake-word listener was passively running would have silently swallowed
whatever you said next (fixed by making the speech-recognition wrapper *retarget* an
already-running session instead of ignoring the new request), and a timing race between
two different browser events that could leave the "is it still listening?" flag
momentarily wrong at exactly the moment the wake-word logic needed to trust it.

### The completeness audit (after Phase 9)

Once every phase was "done," the whole 51-item feature list, the full list of API
routes, the complete voice-command grammar, and the project's file structure were
checked against the *actual code* — not against memory of what had been built — using
two independent automated audits. This found four real, concrete gaps:

1. **Two API routes that existed only as an empty placeholder file** since Phase 0,
   despite the logic they were meant to expose having existed since Phase 3. Both were
   filled in.
2. **BCC by voice** — the feature was literally named "Add CC / BCC by voice," but only
   CC had ever actually been wired to a voice command; the `bcc` field on every draft was
   genuinely dead code. Fixed as an exact mirror of how CC already worked, including
   making sure a BCC'd recipient is read back out loud before "send" is honoured — a
   blind user still has to hear who's BCC'd, even though the other recipients never will.
3. **A command the app itself tells users to say** ("keep going," after an optional
   auto-stop-on-silence feature triggers) had never actually been registered anywhere,
   so saying it risked the literal words becoming part of a composed email.
4. **Reply-all and forward** — only a plain single-person reply had been built; both
   were explicitly deferred at the time as a scope decision, and were built now on
   request. Reply-all correctly includes everyone the original message went to while
   excluding both the sender (who's already the primary recipient) and your own address
   — which required verifying, against the real Gmail API's actual behaviour, that
   fetching your own address needed no new permission and wouldn't force everyone to
   reconnect their Gmail account again.

---

## 4. Testing

**305 automated tests, all of them offline** — the test suite forces both `FAKE_AI` and
`FAKE_GMAIL` to `1` and a fresh in-memory database before a single line of the app's own
code is ever imported, specifically so a test can never accidentally make a real network
call. The tests run in under three seconds.

The testing style throughout is: test the small, pure functions directly first (does
this specific phrase map to the right command? does this specific MIME structure extract
the right text? does this specific time phrase parse correctly?), then test full,
realistic multi-turn conversations through the actual HTTP endpoint, asserting that the
spoken response is always well-formed and never contains a raw error.

There is deliberately **no automated test for the real browser speech/microphone
behaviour** (the wake word, the live screen-reader experience) — that genuinely can't be
driven from a test suite, and the README has a precise manual test script for exactly
those parts instead.

---

## 5. What's honestly not built, and why

- **F51 (a spoken PIN before sending anything that looks sensitive)** — the Phase 9
  stretch goal that wasn't chosen. The wake word was picked instead, deliberately, per
  your own decision.
- **Reconnecting Gmail is, and will always have to be, a sighted step.** The only
  interactive OAuth flow Google's library still offers needs a real browser window; there
  is no way around that through voice alone, and the app says so plainly rather than
  pretending.
- **Opening a file-attachment picker needs one real, manual tap.** Same underlying
  reason as OAuth — a browser will not open a native file dialog in response to
  anything except a genuine, synchronous click.
- **A fresh (not reply) email's tone can only be *set* as a field default from past
  behaviour, not used to actually reword the body.** By the time the system knows who
  you're emailing, the AI has usually already written the body — there's no clean way to
  feed the learned tone back into wording it hadn' known about yet, for a brand-new
  message specifically (replies don't have this limitation, since the recipient is
  already known before anything gets written).
- **Frequently-used phrases are tracked but never auto-inserted anywhere**, by your own
  explicit choice — it's groundwork for a future "use my usual sign-off"-style command,
  not a finished feature on its own.
- **The wake word only works reliably with the browser tab focused and in the
  foreground** — browsers deliberately throttle background-tab microphone access, and
  that's not something fixable from inside the app itself.

---

## 6. Running it

See `README.md` for the exact commands. In short: `uvicorn backend.main:app --reload`,
then open `http://localhost:8000` in Chrome or Edge — there is no separate frontend
server, by design; FastAPI serves the HTML/CSS/JS directly, since the microphone
requires a secure context that only a real server (not a `file://` page) provides.
