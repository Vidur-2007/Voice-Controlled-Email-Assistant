# Voice Email Assistant

A voice-controlled email client built for blind and visually-impaired users. Everything
— composing, editing, sending, reading your inbox, replying, attaching files, scheduling
sends — is designed to be done entirely by voice, with audio feedback for every state
change. There is no visual email client here; the on-screen transcript log is a
convenience for sighted developers, not the primary interface.

Built in phases against `PROJECT_BUILD_SPEC.md`, which remains the authoritative design
reference for anyone extending this project.

## Quick start

```bash
git clone <this repo>
cd voice-email-assistant
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # both FAKE_AI=1 and FAKE_GMAIL=1 — runs with zero setup
python -m backend.data.store --seed
uvicorn backend.main:app --reload
```

Open `http://localhost:8000` in Chrome or Edge (Web Speech API support is required —
Firefox and Safari aren't supported, and the app says so if you load it in one). Tap the
microphone button, or Tab to it and press Enter. **Never open `index.html` directly via
`file://`** — the microphone needs a secure context, which only a real server provides.

With both `FAKE_AI=1` and `FAKE_GMAIL=1` (the `.env.example` default), the entire app
works offline: composing, editing, sending, reading a seeded fake inbox, scheduling —
none of it needs Ollama, a Gmail account, or any network access. This is deliberate
(§5 of the spec) so the interaction design can be built and tested before any real API
access exists, and so the demo always has an offline fallback.

To use the real AI composer, install [Ollama](https://ollama.com), run
`ollama pull llama3.2:3b`, and set `FAKE_AI=0`. To send real email, follow the Gmail
setup below and set `FAKE_GMAIL=0`.

## Running tests

```bash
pytest -q
```

272 tests, all offline — **no test may make a network call** (enforced by `tests/
conftest.py` forcing `FAKE_AI=1`/`FAKE_GMAIL=1`/an in-memory database before any
`backend` import happens).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `FAKE_AI` | `1` | `0` to use a real Ollama (or Gemini) model instead of the deterministic offline composer. |
| `FAKE_GMAIL` | `1` | `0` to send real email via Gmail instead of writing to `outbox.jsonl`. |
| `LLM_PROVIDER` | `ollama` | `ollama` or `gemini` (Gemini is an unconfigured stub — see Known limitations). |
| `LLM_MODEL` | `llama3.2:3b` | Never hardcoded elsewhere — this is the one place it's set. |
| `OLLAMA_HOST` | `http://localhost:11434` | |
| `LLM_KEEP_ALIVE` | `30m` | Keeps the model resident between calls; avoids a slow reload. |
| `LLM_NUM_PREDICT` | `320` | Hard cap on generated tokens — latency *and* accessibility (a shorter cap means a shorter spoken result). |
| `LLM_TIMEOUT_S` | `120` | CPU inference is slow; don't set this low. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | empty | Only used if `LLM_PROVIDER=gemini`. |
| `GMAIL_CREDENTIALS_PATH` | `credentials.json` | A Desktop-app-type OAuth client — see Gmail setup. |
| `GMAIL_TOKEN_PATH` | `token.json` | Written on first successful connect; never commit it. |
| `DB_PATH` | `app.db` | SQLite file — contacts, aliases, prefs, tone history, phrases, scheduled sends. |
| `OUTBOX_PATH` | `outbox.jsonl` | Where `FAKE_GMAIL=1` writes instead of calling the real API. |
| `ATTACHMENTS_DIR` | `attachments` | Where uploaded attachments are saved (F30). |
| `SCHEDULER_POLL_S` | `30` | How often the scheduled-send background thread checks for due sends (F35). |
| `SILENCE_STOP_MS` | `0` | `0` disables auto-stop on silence (F10); `2500` is the recommended value if enabled. |
| `USER_FIRST_NAME` | empty | Used for email sign-offs. Empty means no sign-off — never a `[Your Name]` placeholder. |

## Gmail setup (for real sending — optional)

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and
   enable the Gmail API.
2. Create an OAuth client of type **Desktop app** (not "Web application" — this is the
   single most common setup mistake, and causes a `redirect_uri_mismatch`).
3. Add your own Google account under the consent screen's **Test users**.
4. Download the client secret JSON and save it as `credentials.json` in the repo root.
5. Set `FAKE_GMAIL=0` in `.env`, start the server, then run:
   ```bash
   curl -X POST http://localhost:8000/api/mail/auth
   ```
   This opens a real browser window for a one-time (or occasional re-) sign-in — see
   Known limitations for why this can't be done by voice.

## Architecture

```
backend/
  main.py            FastAPI app: routers, static mount, health, the scheduled-send poller
  models.py           every Pydantic contract — the single source of truth
  commands.py          deterministic command grammar, matched before any model call
  errors.py            exception -> spoken-sentence mapping
  speechify.py          every function that builds spoken text (readback, inbox listing, ...)
  session.py            in-memory per-session conversation state
  text_correction.py    F9 — "no wait, change that to..." preprocessing
  attachments.py         F30 — saved files + "last attachment" tracking
  ai/
    provider.py          THE only LLM call site (swap Ollama/Gemini here, nowhere else)
    compose.py            draft composition, fake/real switch
    edit.py               conversational editing, fake/real switch
    mode_detect.py         dictation-vs-brief classification
    contacts_nlp.py         AI-assisted contact disambiguation (only when deterministic rules can't decide)
    summarize.py            inbox thread summarisation
    prompts.py / schemas.py every system prompt and structured-output schema
  data/
    store.py              sqlite3 schema + singleton connection
    contacts.py             fuzzy contact search, aliases, groups
    prefs.py                 F42/F44/F45 — tone history, phrase bookkeeping, rate persistence
  gmail/
    auth.py                OAuth flow
    send.py                 real + fake send/save-draft
    inbox.py                 real + fake list/read/archive/mark-read
    schedule.py               time parsing + the scheduled-send table
    fake.py                    the FAKE_GMAIL=1 backend (outbox.jsonl + a fake inbox)
  routes/
    voice.py              POST /api/turn — THE orchestrator
    mail.py                 /api/mail/* — direct access for testing without the frontend
    prefs.py                  /api/prefs — speech-rate persistence
    draft.py                   /api/draft/* — direct compose/edit access

frontend/               vanilla JS, no build step, no framework
  index.html               markup — every control a real <button>
  app.js                    the client state machine
  speech.js / tts.js         SpeechRecognition / SpeechSynthesis wrappers
  a11y.js                    the one live region
  cues.js                    WebAudio tone cues
  api.js                     fetch wrappers that never throw
  styles.css                 light/dark theming, reduced-motion support
```

## Accessibility

This app is built audio-first, not as a visual email client with voice bolted on.

- **Tap the mic button once to start, once to stop** (rule A1) — never press-and-hold.
  `Enter`/`Space` work the same way when the button has focus.
- **`Escape` always stops** whatever the app is doing (speaking, listening, thinking)
  without touching your draft — say "cancel" if you actually want to discard it.
- **Audio cues**: a start beep (880 Hz) on listening, a stop beep (660 Hz) when it
  stops, an error tone (220 Hz, lower and longer) on any failure, a distinct two-tone
  "working" sound if anything takes over 1.5 seconds (so silence never reads as "it's
  frozen"), and a distinct two-tone "wake" chime (740 Hz, quicker and higher than the
  working sound) when the wake word is heard.
- **Say "help" at any point** — it lists only the commands that are actually usable in
  whatever you're doing right now, not a fixed list.
- **Every error is spoken as a complete sentence** that states whether your email was
  sent — never a stack trace, an HTTP code, or silence.
- Tested against the full command grammar and error-message table with automated
  tests (`tests/test_commands.py`, `tests/test_error_table.py`); the screen-reader pass
  itself needs a human (see below).

### Running the screen-reader pass yourself

1. Start NVDA (Windows, free) or VoiceOver (`⌘F5` on macOS).
2. Load the app and run through: compose an email to an ambiguous contact (triggers
   disambiguation), have it read back, say "make it more formal", say "read the subject
   again", say "send", then "read my unread mail", "summarise this one", and "help".
3. Confirm at every step: nothing is ever announced twice, every state change (listening
   → thinking → speaking → ready) is audible, Tab alone reaches every control in a
   sensible order, and you never need to look at the screen.
4. The actual gate for this phase: have someone who has never seen this app complete a
   send with their monitor off.

## Known limitations (flagged deliberately, not oversights)

- **Reconnecting Gmail is a sighted, one-time step.** `InstalledAppFlow.run_local_server()`
  is the only interactive OAuth flow Google's library still offers (`run_console()` was
  removed) — there's no way to drive a real Google consent screen through voice alone.
  Say "reconnect my email" and the app tells you this honestly rather than trying and
  silently failing.
- **Attaching a file needs one manual tap.** Opening a native OS file picker requires a
  genuine, synchronous browser click — by the time a voice turn's response comes back,
  that permission has expired. Saying "attach a file" points your next Tab/Enter at the
  real "Attach a file" button instead of pretending to open a picker it can't.
- **Tone learning (F42) only reaches the generated wording for replies**, not fresh
  compositions. A reply's recipient is known before the AI writes anything, so a learned
  tone can genuinely shape the wording. A fresh email's recipient isn't resolved until
  *after* the AI already wrote the body (recipient-hint extraction and body generation
  happen in one model call), so a learned tone there only sets the `tone` field — it
  doesn't retroactively reword anything. Both are exercised by `tests/test_turn_flow.py`.
- **Frequent phrases (F44) are bookkeeping only.** The app tracks recurring sign-offs
  and openers (`phrases` table) but never auto-inserts one into a generated email — a
  deliberate choice, so no real outgoing email's wording changes based on past behaviour
  without an explicit command that turn. This is groundwork for a future voice command
  (e.g. "use my usual sign-off"), not a finished feature.
- **Uploaded attachment files aren't automatically cleaned up.** They're kept so "attach
  the last document I mentioned" can reuse a file across multiple emails in one browser
  session; for a local single-user app, slow disk growth over a long time is a real but
  low-severity concern, better solved later (e.g. a startup sweep) than built now.
- **The Gemini fallback (`LLM_PROVIDER=gemini`) is an intentionally unconfigured stub.**
  Ollama already works locally and for free; the branch exists so adding a real API key
  later is a config change, not a rewrite, but it isn't exercised by anything today.
- **Mid-speech correction ("no wait...") is a text heuristic, not a live interrupt.**
  It can very rarely misfire on genuine dictated content that happens to contain the
  same marker phrase with a different meaning — accepted, since a true live-audio
  interrupt isn't something this turn-based architecture has a way to do.
- **The wake word only works reliably with the tab focused and in the foreground.**
  Browsers throttle or block `SpeechRecognition` from restarting in a backgrounded or
  minimized tab — a real, documented browser limitation, not a bug in this app. See the
  Wake word section below for the full set of wake-word-specific limitations.

## Wake word ("hey ultron") — F11, Phase 9 stretch

Phase 9 is the spec's final, optional stretch phase (F11 wake word, F51 a spoken PIN —
"do one, well, or neither"). The wake word is built; the spoken PIN is not.

**Opt-in, off by default.** Tap "Enable wake word" in the action row. The first time you
turn it on, the app speaks a full disclosure, in full, before anything else — this is a
genuinely different privacy posture from the rest of the app:

> Wake word on. From now on, say "hey ultron" anytime to start talking, even without
> tapping the button — your microphone will stay on and keep listening for that phrase
> while the app is otherwise idle, and what it hears gets sent to your browser's speech
> service the same way it already does when you're actively using the app. Say "hey
> ultron" on its own to start listening, or say "hey ultron" followed by what you want
> to do. Tap this button again to turn it off.

That's not boilerplate — **Chrome's built-in speech recognition sends audio to Google's
servers for processing; it is not on-device.** Enabling this means continuous audio
streaming to that service whenever the app is idle, not just while you're actively
giving it a command. Disabling it (tap the same button again) stops that immediately.

**Two ways to use it**, both handled the same way a tap would be:
- Say "hey ultron" alone → the app starts listening for your actual command, exactly as
  if you'd tapped the mic.
- Say "hey ultron" and your command in one breath ("hey ultron tell John I'll be late")
  → it skips straight to composing, no extra round-trip.

Saying anything that doesn't contain "hey ultron" while it's armed produces **total
silence** — no cue, no announcement, nothing sent anywhere. Ambient conversation in the
room must never produce an audible reaction or a server call, or this would be
unusable.

### Known limitations specific to the wake word

- **Reliability depends on the browser tab staying focused and foregrounded.** This is
  an inherent Web Speech API / browser-throttling constraint (confirmed via current
  research into Chrome's background-tab behavior), not something fixable in a
  vanilla-JS, no-build-step app — production wake-word systems typically use a
  dedicated on-device model for exactly this reason.
- **Detection is a plain, case-insensitive substring match on "hey ultron."** No fuzzy
  tolerance for a mis-transcription (e.g. "hey ultra") — it relies on Chrome's speech
  recognizer getting those two words right.
- **Continuous recognition is laggier than a real wake-word engine.** Chrome's
  `continuous` mode tends to wait for a pause before finalizing a result, so detection
  isn't instantaneous the way a dedicated wake-word model would be.

### Testing it yourself

1. Tap "Enable wake word" — confirm the full disclosure above is spoken once, and the
   button's label/`aria-pressed` flips to "Disable wake word."
2. With the app idle (don't tap the mic), say "hey ultron" alone — confirm the wake
   chime plays, then it starts listening for a real command exactly like a tap would.
3. Say "hey ultron tell John I'll be late" in one breath — confirm it composes directly
   without a separate "now what?" step.
4. With wake word on and the app idle, say something unrelated (e.g. talk to someone
   else in the room) — confirm total silence: no cue, no transcript log entry.
5. While it's passively listening, tap the mic button normally — confirm it correctly
   starts a real command turn (this exercises a real fix in `speech.js`: without it, a
   tap while the passive listener is running would silently swallow whatever you say
   next instead of sending it anywhere).
6. Tap "Disable wake word" mid-utterance (say part of something, then tap quickly) —
   confirm it stays off and doesn't silently re-arm itself.
7. Background or minimize the tab for a minute with wake word on, then come back and
   say "hey ultron" — this is expected to be unreliable per the limitation above, not a
   bug to report.
