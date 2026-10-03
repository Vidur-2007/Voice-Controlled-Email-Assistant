# Voice-Controlled Email Assistant — Complete Build Specification

> **You are Claude Code. This file is your complete brief.**
> Read it end to end before writing any code. It contains the product definition, the
> binding design rules, the architecture, every feature, the exact build order, and the
> gate that must pass before each phase is considered done.
>
> Build **one phase at a time**. Do not skip ahead. Do not start a phase until the previous
> phase's gate passes and the developer has confirmed it.

---

# PART I — WHAT WE ARE BUILDING

## 1. The product in one paragraph

A voice-first email client **for blind and visually impaired users**. The user speaks to
compose, review, edit, send and read email. **No visual interaction is required at any
point in any flow.** This is not voice control added to an email app — accessibility is the
primary design constraint, and every decision must be evaluated against the question
*"does this work for someone who cannot see the screen at all?"*

Built and maintained by a **single developer**. There is no team split; the layer
boundaries in this document exist for testability and for keeping the code comprehensible,
not for dividing work.

## 2. Why the design is what it is

Six empirical findings from the literature constrain the design. They are not background —
they dictate specific behaviour, and you must not "simplify" them away.

| Finding | What it forces |
|---|---|
| Blind users catch only **~40% of speech-recognition errors** when reviewing by audio, with no advantage over sighted users despite far more experience with synthetic speech | Readback alone is not a sufficient safety net. High-risk fields (recipient) must be surfaced **separately and first**, never buried in continuous prose. |
| **Correction cost**, not recognition accuracy, is what makes speech input unusable | Every flow needs a cheap, obvious repair path. "Start over" must always work. |
| LLM-written email is **~167% more verbose** than human-written email | Generated drafts must be explicitly length-constrained. Verbosity is an accessibility cost when every word must be heard. |
| Blind expert listeners comprehend speech at **up to ~22 syllables/second**; preferences vary widely | Speech rate must be user-adjustable and persisted. Never ship a fixed rate. |
| Assistants that **explicitly acknowledge and repair** their errors sustain interaction better than those that fail silently | Every failure is spoken. Never fail silently. Ever. |
| Accessibility **overlays** bolted onto inaccessible interfaces conflict with assistive tech and make things worse | Build audio-first from the ground up. Do not build a normal email UI and add voice. |

---

# PART II — BINDING RULES (never violate these)

These are decided. Do not re-lit­igate them, and do not propose patterns that violate them
even when they are common in mainstream voice-assistant examples.

## 3. Accessibility rules

| # | Rule | Why |
|---|---|---|
| **A1** | **Tap-to-toggle, never press-and-hold.** The mic button starts on one tap and stops on a second tap. `Enter` and `Space` activate it when focused. | Screen readers navigate by swipe and activate by tap. Sustained-press fights that model. |
| **A2** | **Exactly one live region in the entire application** — a single `<div id="status" role="status" aria-live="polite">` that is both the visible status text and the only announced element. | Two live regions make screen readers announce everything twice. |
| **A3** | **Distinct audio cue per event type**, not per state: start beep (880 Hz), stop beep (660 Hz), error tone (220 Hz, longer, lower). | A failure must be identifiable by ear alone, without parsing a sentence. |
| **A4** | **A spoken `help` command must exist** and must list the commands available *in the current phase*, not a fixed list. | Discoverability is the single biggest failure of mainstream voice assistants for blind users. |
| **A5** | **Errors are always spoken. Never fail silently.** Every `catch` ends in a spoken sentence. | Silent failure is the worst outcome in an audio-only interface. |
| **A6** | **Readback before send is mandatory and cannot be skipped or disabled.** | Primary safety net against misrecognition. |
| **A7** | **Every interactive control is a real `<button>`**, never a styled `<div>`. Never suppress focus outlines. Use native `aria-pressed` on the mic toggle. | Correct role and state for free. |
| **A8** | **Respect `prefers-reduced-motion`** for any animation. | Relevant to low-vision users. |
| **A9** | **No colour-only signalling.** Anything shown by colour is also in the status text and in audio. | |
| **A10** | **Never use `alert()`, `confirm()` or `prompt()`.** All prompts are spoken. | Modal dialogs block the app and are hostile to screen readers. |
| **A11** | **Every backend `message` string is spoken aloud verbatim.** It must be a complete, plain English sentence — no stack traces, no HTTP codes, no JSON, no `null`, no snake_case identifiers. | |
| **A12** | **Normalise text for speech before speaking it.** `john.smith@example.com` → "john dot smith at example dot com". Strip markdown. Convert paragraph breaks to audible pauses. | Raw addresses are unintelligible through TTS. |
| **A13** | **The application must cooperate with screen readers, not fight them.** Test with NVDA or VoiceOver. If both the app and the screen reader speak, that is a bug. | |
| **A14** | **Any operation that takes longer than 1.5 seconds must be audibly acknowledged within 1.5 seconds** — a short spoken phrase ("Writing that now") or a distinct working tone, repeated or sustained until the result arrives. | Silence is indistinguishable from failure when you cannot see a spinner. This matters more on a CPU-only machine, where drafting takes 10–20 s. |

## 4. Engineering rules

- **Python 3.11+**, FastAPI, Pydantic v2. **Vanilla JavaScript frontend — no build step, no npm, no bundler, no framework.**
- **FastAPI serves the frontend itself** from `/`. Never open `index.html` via `file://` (microphone access requires a secure context), and never run a second dev server (that adds CORS problems for no benefit).
- **Pydantic v2 syntax only**: `model_dump()`, `model_validate()`. Never `.dict()`, never `.parse_obj()`.
- **All route handlers are plain `def`, not `async def`.** The Ollama and Google clients used here are synchronous; FastAPI runs sync handlers in a threadpool. Mixing sync SDK calls into `async def` blocks the event loop.
- **Zero paid components.** Every dependency must be free. The language model runs locally via Ollama. Never introduce a service that requires billing.
- **Never hardcode a model name.** Use `settings.llm_model`, set in exactly one place (`config.py`).
- **Never ask the model for JSON in a prose response and parse it.** Always pass a JSON Schema through the provider's structured-output parameter, so the result is schema-valid by construction.
- **All language-model calls go through `backend/ai/provider.py`.** No module imports an LLM SDK directly. This is what makes the cloud fallback a config change rather than a rewrite.
- **Secrets live in `.env` only.** `.env`, `token.json`, `credentials.json`, `*.db` are gitignored and must never be committed or printed to logs.
- **Every module must import cleanly with no credentials present.** Construct API clients lazily inside functions, never at import time.

## 5. The offline-mode rule (most important build rule)

The application **must run end to end with zero credentials**. Two environment flags:

```
FAKE_AI=1      # ai/* returns deterministic canned drafts, no network call
FAKE_GMAIL=1   # gmail/* writes to outbox.jsonl, no network call
```

- `.env.example` ships with **both set to 1**.
- **Every test runs with both set to 1. No test may make a network call.**
- If `FAKE_AI=0` and the API key is missing, the app must still **start** and return a spoken error — it must not crash on boot.
- Fakes live beside the real implementations and are selected by a single `if settings.fake_ai:` at the top of each public function.

This is what lets you build and test the interaction design before any API access exists, keeps the test suite fast and offline, and gives the demo a fallback if the network dies.

---

# PART III — COMPLETE FEATURE LIST

Every feature the product must have. Each has an ID; the phase that delivers it is in the
last column. **Nothing here is optional except the rows marked STRETCH.**

## 6. Composition

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F1 | **Dictation mode** | User speaks the email word for word. Wording is preserved verbatim — only capitalisation, punctuation and obvious homophone errors are corrected, and filler words ("um", "uh") stripped. Never rephrase or summarise. | 3 |
| F2 | **Brief mode (AI-composed)** | A short spoken instruction ("tell my manager I'll be late") is expanded by the language model into a complete, well-structured email. | 3 |
| F3 | **Automatic mode detection** | Heuristics first: explicit triggers → decided; under 15 words and casual → brief; over 40 words → dictation; otherwise ask the model. | 3 |
| F4 | **Manual mode override** | "dictate this" / "write it for me" force a mode at any time. | 3 |
| F5 | **Ask on ambiguity** | If detection confidence is below 0.6, ask aloud: *"Do you want to dictate this word for word, or should I write it for you?"* | 3 |

## 7. Voice input

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F6 | **Continuous natural speech-to-text** | Not limited to short rigid commands. `continuous = true`, `interimResults = true`. | 2 |
| F7 | **Tap-to-toggle activation** | Rule A1. Also `Enter`/`Space` when the button has focus, and `Escape` to cancel from anywhere. | 2 |
| F8 | **Tolerates pauses** | A natural pause must not end the turn. | 2 |
| F9 | **Mid-speech correction** | "no wait, change that to…" is handled as a revision rather than literal text. | 7 |
| F10 | **Optional auto-stop on silence** | Implemented but **disabled by default** (`SILENCE_STOP_MS=0`). When enabled, 2500 ms, timer resets on any interim result, and after an auto-stop the app says *"I stopped listening because it went quiet. Say 'keep going' to add more."* | 2 |
| F11 | **Wake word** | STRETCH. Only after Phase 8 is green. | 9 |

## 8. Contacts

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F12 | **Spoken name → email address** | "email John" resolves to an address. | 4 |
| F13 | **Ambiguity clarification** | *"Which John — Smith, or Carter? Say the last name, or say one or two."* Always offer an ordinal as well as a name, because the user cannot read a list off the screen. | 4 |
| F14 | **Relationship aliases** | "my manager", "my supervisor" resolve via an alias table before fuzzy matching. | 4 |
| F15 | **Group / distribution lists** | "email the whole team" expands to a group. | 4 |
| F16 | **Unknown contact handling** | *"I don't have a contact called Priya. Who should I send this to?"* — then accept a spelled-out or dictated address. | 4 |

## 9. AI email generation

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F17 | **Intent and detail extraction** | Pull recipient hint, intent and key details from a casual spoken brief. | 3 |
| F18 | **Automatic subject line** | Under 60 characters. Never duplicated inside the body. | 3 |
| F19 | **Body expansion** | Plain prose. **No markdown, no bullet characters, no emoji, and never placeholders like `[Your Name]`.** Sign off with the user's first name if known, otherwise no sign-off. | 3 |
| F20 | **Tone control by voice** | "make it formal", "make it friendly", "make it firm", "make it more polite", "make it apologetic". | 3 |
| F21 | **Length control by voice** | "keep it short", "make it shorter", "add more detail". Length is actively constrained by default — see §2. | 3 |
| F22 | **Reply context awareness** | When replying, the original thread text is fed into the prompt so the reply is coherent. | 6 |

## 10. Spoken confirmation and readback

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F23 | **Full readback before send** | Recipient first, then subject, then body, then the confirmation prompt. Mandatory (A6). | 2 |
| F24 | **Explicit verbal confirmation** | Only the word "send" (or a listed synonym) in the `awaiting_confirm` phase actually sends. Enforced **server-side**, not just in the UI. | 2 |
| F25 | **Partial review on request** | "read the subject again", "read the body", "who is it going to". | 2 |
| F26 | **Length warning** | A body over 120 words is prefaced with *"The message is about N words. Here it is."* so the user knows how long to listen. | 2 |

## 11. Conversational editing

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F27 | **Revision without starting over** | "make it shorter", "remove the last sentence", "add that I'll call in". | 3 |
| F28 | **Formatting commands** | "new paragraph" (dictation mode). | 7 |
| F29 | **Add CC / BCC by voice** | "add cc", "copy in Sarah". | 7 |
| F30 | **Attach a file by voice** | Voice-triggered file picker, and "attach the last document I mentioned". | 7 |
| F31 | **Undo / redo by voice** | Push a copy of the draft before every mutation. "Undone. *(one-line summary of the restored draft)*." If empty: "There's nothing to undo." | 3 |
| F32 | **Start over** | Clears the draft and returns to idle. Must always work from any phase. | 1 |

## 12. Sending and email actions

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F33 | **Send** | | 5 |
| F34 | **Save as draft** | Real provider-side draft. | 5 |
| F35 | **Schedule send** | "send this at 5pm" — store and dispatch later. | 7 |
| F36 | **Reply / reply-all / forward** | Correct threading via `threadId`. | 6 |
| F37 | **Cancel** | Discards the draft; confirms aloud that nothing was sent. | 1 |

## 13. Reading incoming mail

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F38 | **Read unread email aloud** | "read my unread mail". | 6 |
| F39 | **Summarise long emails** | "summarise this one" — short digest before optionally reading in full. | 6 |
| F40 | **Inbox navigation by voice** | "next email", "previous", "read sender", "archive this", "mark as read". | 6 |
| F41 | **Plain-text extraction** | Walk MIME parts recursively, prefer `text/plain`, strip tags if only HTML exists. **Never speak raw HTML.** | 6 |

## 14. Personalisation and learning

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F42 | **Tone learning** | Store the chosen tone per recipient; default to it next time. | 8 |
| F43 | **Frequent contacts** | Rank contact matches by use count, so common recipients win ties. | 8 |
| F44 | **Frequently used phrases** | Store and reuse recurring sign-offs and openers. | 8 |
| F45 | **Speech rate persistence** | Remember the user's preferred rate across sessions. | 8 |

## 15. Accessibility and safety

| ID | Feature | Detail | Phase |
|---|---|---|---|
| F46 | **Full TTS feedback at every step** | No visual dependency anywhere. | 2 |
| F47 | **Screen reader compatibility** | NVDA, VoiceOver, TalkBack. No double announcements. | 8 |
| F48 | **Clarification instead of silent failure** | Rule A5. | 1 |
| F49 | **Spoken help listing current commands** | Rule A4. | 1 |
| F50 | **Unsupported-browser fallback** | If `SpeechRecognition` is missing: render a message, announce it, and speak it if synthesis is available. Never leave a dead button. | 2 |
| F51 | **Spoken PIN before sending sensitive content** | STRETCH. Triggered only by detected sensitive keywords. Must be described honestly as a speed bump, not real authentication. | 9 |

---

# PART IV — ARCHITECTURE

## 16. Layers

```
USER (speaks / listens only)
   │
┌──┴─────────────────────────────────────────────────────────┐
│ LAYER 1 · INTERACTION  (browser, vanilla JS, no build step)│
│   Microphone Capture · Client State Machine · Speech Output │
│   Audio Cues · Status Announcer (single live region)        │
├────────────────────────────────────────────────────────────┤
│ LAYER 2 · ORCHESTRATION  (FastAPI)                          │
│   Turn Orchestrator (single entry point) · Command Grammar  │
│   Conversation State · Readback Builder                     │
├────────────────────────────────────────────────────────────┤
│ LAYER 3 · LANGUAGE PROCESSING                               │
│   Mode Detection · Draft Composition · Conversational Edit  │
│   Contact Resolution · Summarisation                        │
├────────────────────────────────────────────────────────────┤
│ LAYER 4 · INTEGRATION AND DATA                              │
│   Mail Service · Inbox Reader · Contact Store · Error       │
│   Translator                                                │
└────────────────────────────────────────────────────────────┘
        ↕ (both replaceable by local stubs)
   Language Model API          Email Provider API
```

**Key structural decision: the command grammar sits in front of the language model, not
behind it.** "Send", "undo", "read it back" are matched deterministically and never reach
the model. This keeps the most frequent interactions instant and predictable, and means a
slow or unavailable model degrades the assistant rather than breaking it.

## 17. Repository layout

Create exactly this. Do not add extra top-level directories.

```
voice-email/
├── PROJECT_BUILD_SPEC.md        # this file
├── README.md                    # written in Phase 8
├── requirements.txt
├── .env.example
├── .gitignore
├── pytest.ini
│
├── backend/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app: routers, static mount, health
│   ├── config.py                # Settings from env — single source of truth
│   ├── models.py                # ALL Pydantic contracts — single source of truth
│   ├── session.py               # ConversationState + in-memory registry
│   ├── errors.py                # SpokenError + exception → speech mapping
│   ├── speechify.py             # text → speakable text; build_readback()
│   ├── commands.py              # deterministic command grammar
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── voice.py             # POST /api/turn — THE orchestrator
│   │   ├── draft.py             # direct draft endpoints (dev/testing)
│   │   └── mail.py              # send, draft, inbox, auth
│   │
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── provider.py          # THE only LLM call site — Ollama, retry, FAKE_AI switch
│   │   ├── prompts.py           # every system prompt as a named constant
│   │   ├── schemas.py           # tool-use JSON schemas
│   │   ├── mode_detect.py       # F3, F5
│   │   ├── compose.py           # F1, F2, F17–F21
│   │   ├── edit.py              # F27, F9
│   │   ├── contacts_nlp.py      # F13
│   │   └── summarize.py         # F39
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── store.py             # sqlite3 schema, migrations, --seed CLI
│   │   ├── contacts.py          # fuzzy candidate search (F12, F14, F15, F43)
│   │   ├── prefs.py             # F42, F44, F45
│   │   └── seed_contacts.json
│   │
│   └── gmail/
│       ├── __init__.py
│       ├── auth.py              # OAuth flow, token.json
│       ├── send.py              # F33, F34, F36
│       ├── inbox.py             # F38, F40, F41
│       ├── schedule.py          # F35
│       └── fake.py              # FAKE_GMAIL backend → outbox.jsonl
│
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── a11y.js                  # the single live region + announce()
│   ├── cues.js                  # WebAudio tones
│   ├── tts.js                   # SpeechSynthesis wrapper + queue
│   ├── speech.js                # SpeechRecognition wrapper
│   ├── api.js                   # fetch wrappers — never throw
│   └── app.js                   # client state machine
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_models.py
    ├── test_speechify.py
    ├── test_commands.py
    ├── test_contacts.py
    ├── test_turn_flow.py
    └── test_mail_fake.py
```

## 18. Dependencies

`requirements.txt` — pin exactly these. Known-compatible.

```
fastapi==0.141.1
uvicorn[standard]==0.52.3
pydantic==2.13.4
python-dotenv==1.2.3
ollama==0.6.3
google-api-python-client==2.198.0
google-auth-oauthlib==1.4.0
google-auth-httplib2==0.4.1
rapidfuzz==3.14.5
pytest==9.1.1
httpx==0.28.1
```

Notes that prevent real errors:
- `httpx` is required by `fastapi.testclient.TestClient`. Omitting it makes every test fail with a confusing error.
- `uvicorn[standard]`, not bare `uvicorn` — the extras include `watchfiles`, without which `--reload` misbehaves.
- **Do not install `pyttsx3`.** TTS is browser-side. `pyttsx3` needs system audio libraries that are usually absent and will fail to build.
- **Do not install `anthropic`, `openai`, or any paid-service SDK.** The language model is local (§19a).
- **Do not install `transformers`, `torch`, or `llama-cpp-python`.** Ollama manages the model; pulling a second inference stack wastes several gigabytes and will not fit alongside the model on an 8 GB machine.
- Do not add `python-multipart` until attachments (F30) are actually implemented.

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.env
token.json
credentials.json
*.db
outbox.jsonl
.pytest_cache/
```

## 19. Configuration — `backend/config.py`

```python
from functools import lru_cache
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()   # must run before Settings is constructed

class Settings(BaseModel):
    # --- language model (free, local by default) ---
    llm_provider: str = "ollama"      # "ollama" | "gemini"
    llm_model: str = "llama3.2:3b"
    ollama_host: str = "http://localhost:11434"
    llm_keep_alive: str = "30m"       # keeps the model resident; avoids a slow reload per call
    llm_num_predict: int = 320        # hard cap on generated tokens — latency AND accessibility
    llm_timeout_s: int = 120          # CPU inference is slow; do not set this low
    gemini_api_key: str = ""          # only used if llm_provider == "gemini"
    gemini_model: str = "gemini-2.0-flash"

    fake_ai: bool = True
    fake_gmail: bool = True
    db_path: str = "app.db"
    gmail_credentials_path: str = "credentials.json"
    gmail_token_path: str = "token.json"
    outbox_path: str = "outbox.jsonl"
    silence_stop_ms: int = 0          # 0 = disabled (F10)
    user_first_name: str = ""         # used for sign-offs (F19)

@lru_cache
def get_settings() -> Settings:
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        llm_model=os.getenv("LLM_MODEL", "llama3.2:3b"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        llm_keep_alive=os.getenv("LLM_KEEP_ALIVE", "30m"),
        llm_num_predict=int(os.getenv("LLM_NUM_PREDICT", "320")),
        llm_timeout_s=int(os.getenv("LLM_TIMEOUT_S", "120")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        fake_ai=os.getenv("FAKE_AI", "1") == "1",
        fake_gmail=os.getenv("FAKE_GMAIL", "1") == "1",
        db_path=os.getenv("DB_PATH", "app.db"),
        gmail_credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json"),
        gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "token.json"),
        outbox_path=os.getenv("OUTBOX_PATH", "outbox.jsonl"),
        silence_stop_ms=int(os.getenv("SILENCE_STOP_MS", "0")),
        user_first_name=os.getenv("USER_FIRST_NAME", ""),
    )
```

`.env.example`:
```
# Both fakes ON by default: the app runs end to end with nothing installed or configured.
FAKE_AI=1
FAKE_GMAIL=1

# ---- Language model: local and free. Set FAKE_AI=0 once Ollama is running. ----
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2:3b
OLLAMA_HOST=http://localhost:11434
LLM_KEEP_ALIVE=30m
LLM_NUM_PREDICT=320
LLM_TIMEOUT_S=120

# ---- Fallback only, if the machine cannot run a local model (§19a). ----
# LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# Set FAKE_GMAIL=0 and place credentials.json in the repo root to send real mail.
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_TOKEN_PATH=token.json

DB_PATH=app.db
OUTBOX_PATH=outbox.jsonl

# 0 disables auto-stop on silence (F10). 2500 is the recommended value if enabled.
SILENCE_STOP_MS=0

# Used for email sign-offs. Leave empty for no sign-off — never "[Your Name]".
USER_FIRST_NAME=
```

## 19a. The language model — free, local, and swappable

**This project has zero paid components.** The model runs on the developer's own machine
through [Ollama](https://ollama.com), which is free and open source. Nothing is trained;
an existing open-weights model is used as-is.

### Setup (the developer does this once)

```bash
# 1. install Ollama from https://ollama.com/download
# 2. pull the model (2.0 GB)
ollama pull llama3.2:3b
# 3. confirm it answers
ollama run llama3.2:3b "Write one sentence."
```

Ollama runs a local server on `http://localhost:11434`. There is no API key, no account,
no rate limit, and no network traffic once the model is pulled.

### Model choice

| Model | Disk | Use when |
|---|---|---|
| **`llama3.2:3b`** | 2.0 GB | **Default.** Fits comfortably in 8 GB RAM alongside the browser. Good instruction-following and summarisation for its size. |
| `qwen2.5:3b` | ~2 GB | Alternative if Llama's drafts feel stilted. Swap by changing `LLM_MODEL` only. |
| `llama3.2:1b` | 1.3 GB | Last resort on a very constrained machine. Draft quality drops noticeably. |
| `llama3.1:8b` | ~4.7 GB | Only on 16 GB+ machines. Better prose, roughly 2–3× slower on CPU. |

Do not pull more than one model unless disk space is plentiful.

### Structured output — the required pattern

Ollama constrains generation to a **JSON Schema** passed in the `format` parameter, which
means **the Pydantic models in §20 are the schema**. No tool-use plumbing, no parsing prose.

```python
# backend/ai/provider.py
from ollama import Client
from pydantic import BaseModel
from backend.config import get_settings

def generate(system: str, user: str, schema_model: type[BaseModel]) -> BaseModel:
    """The ONLY place an LLM is called. Returns a validated Pydantic object."""
    s = get_settings()
    if s.llm_provider == "ollama":
        client = Client(host=s.ollama_host, timeout=s.llm_timeout_s)
        resp = client.chat(
            model=s.llm_model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            format=schema_model.model_json_schema(),   # ← grammar-constrained decoding
            keep_alive=s.llm_keep_alive,
            options={"num_predict": s.llm_num_predict, "temperature": 0.4},
        )
        return schema_model.model_validate_json(resp.message.content)
    elif s.llm_provider == "gemini":
        ...   # see §19b
    raise ValueError(f"unknown provider {s.llm_provider}")
```

Schema models live in `backend/ai/schemas.py` as plain Pydantic classes:

```python
class DraftFields(BaseModel):
    recipient_hint: str     # person named, as spoken; "" if none
    subject: str            # under 60 characters
    body: str               # plain prose, no markdown, no placeholders
    tone: Tone

class ModeChoice(BaseModel):
    mode: Literal["dictation", "brief", "unclear"]
    confidence: float

class ContactChoice(BaseModel):
    email: str              # "" if still ambiguous
    question: str           # spoken disambiguating question, "" otherwise
```

**Validate the schema is actually being honoured.** Some smaller models ignore constraints
under load. `provider.generate()` must catch `ValidationError`, retry **once** with the
schema restated in the user message, and on a second failure raise a `SpokenError`
carrying *"I couldn't write that properly. Could you say it again?"*

### 19b. Cloud fallback — only if the local model will not run

If the machine cannot run a 3B model, set `LLM_PROVIDER=gemini` and put a key from
Google AI Studio (free tier, no billing account) in `GEMINI_API_KEY`. Implement it in the
same `provider.generate()` function using Gemini's `response_schema` parameter, which takes
the same Pydantic JSON schema. **No other file changes.** This path is a fallback, not the
default — it is rate-limited and needs a network connection during the demo.

### 19c. Latency budget — this is a design constraint, not an afterthought

On a CPU-only 8 GB machine a 3B model generates roughly **8–15 tokens per second**. A
120-word email is ~160 tokens, so **drafting takes 10–20 seconds**. That is a long silence
in a voice interface. Four mitigations, all mandatory:

1. **Most turns never reach the model.** The command grammar (§22) handles "send", "undo",
   "read it back", tone and length commands deterministically. Only composition, free-form
   edits, contact disambiguation and summarisation incur model latency.
2. **Cap output length.** `num_predict=320` is a hard ceiling, and the prompts instruct
   brevity. This is required for accessibility anyway (§2) — the two goals coincide.
3. **Acknowledge within 1.5 seconds (rule A14).** Speak "Writing that now" or play a
   sustained working tone the moment a model call starts. Never leave dead air.
4. **Keep the model warm.** `keep_alive="30m"` prevents Ollama unloading the model between
   calls; a cold load adds several seconds to the first request.

Measure it: `provider.generate()` must log elapsed milliseconds for every call so Phase 3's
gate can report real numbers.

## 20. Data contracts — `backend/models.py`

Single source of truth. Everything imports from here.

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

Phase = Literal[
    "idle",             # nothing in progress
    "awaiting_mode",    # asked dictation-or-brief
    "clarifying",       # asked "which John?"
    "awaiting_address", # asked for an unknown contact's address
    "review",           # draft exists
    "awaiting_confirm", # readback done, waiting for "send"
    "reading_inbox",    # navigating messages
]

Tone   = Literal["neutral", "formal", "friendly", "firm", "apologetic"]
Length = Literal["short", "normal", "detailed"]


class Draft(BaseModel):
    recipient: str = ""            # resolved address, or "" if unresolved
    subject: str = ""
    body: str = ""
    recipient_name: str = ""       # human name, for speaking aloud
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    tone: Tone = "neutral"
    length: Length = "normal"
    thread_id: Optional[str] = None    # set when replying
    send_at: Optional[str] = None      # ISO 8601, for scheduled send


class TurnRequest(BaseModel):
    session_id: str = Field(min_length=1)
    transcript: str = ""

class TurnResponse(BaseModel):
    speech: str                    # THE string the client speaks. Never empty.
    phase: Phase = "idle"
    draft: Optional[Draft] = None  # optional on-screen display only
    awaiting_confirmation: bool = False
    listen_again: bool = True      # hint: reopen the mic after speaking
    ok: bool = True                # false = this turn failed; speech explains it


class MailResult(BaseModel):
    success: bool
    message: str                   # a complete, speakable English sentence


class ContactCandidate(BaseModel):
    name: str
    email: str
    score: float = 0.0

class InboxItem(BaseModel):
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    unread: bool = True
```

**Invariants enforced by tests:**
- `TurnResponse.speech` is never empty and never contains `{`, `}`, `None`, `null`, `Traceback`, or an uppercase HTTP status word.
- `Draft.recipient/subject/body` are always `str`, never `None`. Empty is `""`.
- `MailResult.message` always ends in `.`, `?` or `!`.

## 21. Complete route inventory

Nothing else exists. Do not invent extras.

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| GET | `/api/health` | – | `{status, fake_ai, fake_gmail, has_gmail_token}` | Defined in `main.py` |
| POST | `/api/turn` | `TurnRequest` | `TurnResponse` | The only endpoint `app.js` needs for composing |
| POST | `/api/draft/compose` | `{transcript, mode?}` | `Draft` | Direct access for testing without the frontend |
| POST | `/api/draft/edit` | `{draft, instruction}` | `Draft` | Same |
| POST | `/api/mail/send` | `Draft` | `MailResult` | |
| POST | `/api/mail/draft` | `Draft` | `MailResult` | Save as provider draft |
| POST | `/api/mail/schedule` | `Draft` | `MailResult` | F35 |
| POST | `/api/mail/auth` | – | `MailResult` | Runs the blocking OAuth flow; sync `def` |
| GET | `/api/mail/inbox` | `?limit=10` | `list[InboxItem]` | F38 |
| GET | `/api/mail/thread/{id}` | – | `{text}` | F22, F39 |
| POST | `/api/mail/archive/{id}` | – | `MailResult` | F40 |
| GET | `/` and static | – | `frontend/` | Mounted **last** |

**Every `/api/mail/*` endpoint returns HTTP 200 with a `MailResult`, even on failure.**
A failure is `{"success": false, "message": "<speakable sentence>"}` — never a 4xx/5xx body.
The client must never branch on a status code.

`build_readback(draft) -> str` lives in `backend/speechify.py`, not in `voice.py`, so both
the turn orchestrator and the inbox reader can use it and it is unit-testable without FastAPI.

## 22. Command grammar — `backend/commands.py`

Parsed **before any model call**. Match case-insensitively against the trimmed transcript.
Accept all listed synonyms.

| Intent | Phrases |
|---|---|
| `SEND` | send, send it, send it now, yes send, go ahead and send |
| `CANCEL` | cancel, never mind, forget it, discard |
| `HELP` | help, what can I say, what are my options |
| `REPEAT` | repeat that, say that again, read it again, read it back |
| `READ_SUBJECT` | read the subject, what's the subject |
| `READ_BODY` | read the body, read the message |
| `READ_RECIPIENT` | who is it going to, read the recipient |
| `UNDO` | undo, undo that |
| `REDO` | redo |
| `RESTART` | start over, scrap that, start again |
| `SAVE_DRAFT` | save as draft, save it for later |
| `TONE_FORMAL` / `FRIENDLY` / `FIRM` / `APOLOGETIC` | make it formal, make it friendly, make it firm, make it more polite |
| `SHORTER` / `LONGER` | make it shorter, keep it short, add more detail |
| `ADD_CC` | add cc, copy in … |
| `NEW_PARAGRAPH` | new paragraph *(dictation mode only)* |
| `ATTACH` | attach a file, attach the last document I mentioned |
| `SCHEDULE` | send this at …, schedule this for … |
| `READ_INBOX` | read my unread mail, check my email |
| `NEXT_EMAIL` / `PREV_EMAIL` | next email, previous email |
| `READ_SENDER` | who is it from, read the sender |
| `ARCHIVE` | archive this, archive it |
| `SUMMARISE` | summarise this one, give me the gist |
| `KEEP_GOING` | keep going *(after an auto-stop, F10)* |
| `RECONNECT` | reconnect my email |

**`SEND` is honoured only in phase `awaiting_confirm`.** In any other phase, respond:
*"I haven't read the message back to you yet. Say 'read it back' first."* This is rule A6 and
must be enforced server-side.

Anything not matching falls through to the language-processing path.

## 23. Conversation state — `backend/session.py`

```python
class ConversationState(BaseModel):
    session_id: str
    phase: Phase = "idle"
    draft: Draft = Draft()
    history: list[Draft] = []        # undo stack
    redo_stack: list[Draft] = []
    candidates: list[ContactCandidate] = []
    mode: Optional[str] = None       # "dictation" | "brief"
    last_speech: str = ""            # for "repeat that"
    inbox: list[InboxItem] = []      # F38–F40
    inbox_index: int = 0
```

Held in a module-level `dict[str, ConversationState]`. In-memory is deliberate — single
user, no database server needed. The frontend generates a UUID once per page load and holds
it in a JS variable (**not** localStorage — unnecessary and unavailable in some contexts).

**Undo:** push a copy of `state.draft` onto `history` **before every mutation**.

## 24. Turn flow — `backend/routes/voice.py`

```
receive {session_id, transcript}
  ├─ empty transcript        → "I didn't catch that. Could you say it again?" (ok=true)
  ├─ matches command grammar → handle deterministically
  └─ otherwise
       ├─ phase == clarifying       → resolve contact from the answer
       ├─ phase == awaiting_address → parse a spoken address
       ├─ phase == awaiting_mode    → set mode, then compose
       ├─ phase == review           → treat as a conversational edit
       ├─ phase == reading_inbox    → treat as an inbox command
       └─ phase == idle             → detect mode → resolve contact → compose → read back
```

After composing, `speech` is built by `build_readback(draft)`:

> "To {recipient_name or speakable address}. Subject: {subject}. Message: {body}.
>  Say send to send it, or tell me what to change."

and `phase` becomes `awaiting_confirm`, `awaiting_confirmation=True`.

## 25. Prompts

Structured output is covered in §19a — every model call goes through
`provider.generate(system, user, schema_model)` and returns a validated Pydantic object.
This section covers only the prompt text.

`backend/ai/prompts.py` holds every system prompt as a named constant. **Every prompt that
produces email text must contain these lines**, because the output is spoken aloud and a
small local model will pad without them:

```
The email you write will be read aloud by a screen reader to a blind user.
Write plain prose only: no markdown, no bullet characters, no emoji, no placeholders
like [Your Name] or [Company], and no subject line inside the body.
Be brief. Aim for under 90 words unless the user asked for detail.
Reply with JSON matching the schema and nothing else.
```

The last line matters more with a 3B model than with a large one: even under schema
constraint, restating the expected shape in the prompt measurably improves adherence.

Required prompts:

- `SYSTEM_COMPOSE` — expand a short spoken brief into a complete email (F2, F17–F19).
- `SYSTEM_DICTATE` — clean a raw transcript into a body **without changing wording**: fix only capitalisation, punctuation and obvious homophone errors, strip filler, apply spoken formatting commands. It must not rephrase, add or summarise (F1).
- `SYSTEM_EDIT` — given a previous draft plus an instruction, return the whole revised draft. Change only what was asked; preserve everything else verbatim (F27).
- `SYSTEM_MODE` — classify a transcript as dictation or brief (F3).
- `SYSTEM_PICK_CONTACT` — choose among candidate contacts or produce a spoken disambiguating question (F13).
- `SYSTEM_SUMMARISE` — condense an email thread to two or three spoken sentences (F39).

## 26. Contact resolution — deterministic first, model second

1. `data/contacts.py::search(hint)` using `rapidfuzz.process.extract` with `scorer=fuzz.WRatio`, `limit=5`.
2. Top score ≥ 90 **and** second < 70 → resolved, no model call.
3. No candidate ≥ 60 → *"I don't have a contact called {hint}. Who should I send this to?"* (phase → `awaiting_address`).
4. Otherwise → `contacts_nlp.resolve(hint, candidates, transcript)` with `PICK_CONTACT_TOOL`. The model sees the whole transcript, so "email John about the quarterly numbers" can pick John from Finance.
5. Aliases (F14) and groups (F15) resolve **before** fuzzy matching.
6. Ties break by `use_count` (F43).

## 27. Storage — `backend/data/store.py`, stdlib `sqlite3` only

```sql
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  group_name TEXT DEFAULT '',
  use_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS aliases (
  alias TEXT PRIMARY KEY,
  contact_id INTEGER NOT NULL REFERENCES contacts(id)
);
CREATE TABLE IF NOT EXISTS prefs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tone_history (
  recipient TEXT PRIMARY KEY,
  tone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phrases (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  use_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scheduled (
  id INTEGER PRIMARY KEY,
  send_at TEXT NOT NULL,
  draft_json TEXT NOT NULL,
  sent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sent_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  recipient TEXT, subject TEXT, tone TEXT
);
```

- Open connections with `sqlite3.connect(path, check_same_thread=False)` — FastAPI's threadpool runs handlers on different threads and the default raises `ProgrammingError`.
- `python -m backend.data.store --seed` creates the schema and loads `seed_contacts.json`.
- **`seed_contacts.json` must include two people named John (Smith and Carter), a `team` group, and a `my manager` alias**, so the ambiguity path (F13) is demonstrable from day one.

## 28. Frontend module specs

### `a11y.js`
`announce(text)` sets `#status.textContent`. Exactly one `#status` element with
`role="status" aria-live="polite"`. If the new text equals the current text, append a
zero-width space so the screen reader re-announces it. Nothing else in the app may have
`aria-live`.

### `cues.js`
WebAudio oscillator, three distinct tones (A3). **The AudioContext must be created inside
the first user-gesture handler**, not at module load, or the browser suspends it and every
cue is silent with no error.

### `tts.js`
```js
export function speak(text, {rate = 1.0} = {}) -> Promise<void>   // resolves on 'end'
export function stopSpeaking()
export function setRate(r)
```
Pitfalls that must be coded around, all real:
- `getVoices()` returns `[]` on first call. Wait for the `voiceschanged` event; fall back to the default voice.
- **Chrome silently stops long utterances after ~15 seconds. Chunk text into sentences of ≤200 characters and queue them**, resolving only after the last chunk ends. Email bodies are long — without this, readback cuts off mid-body, which is the single most damaging bug in this application.
- Run a keepalive while speaking: `setInterval(() => { speechSynthesis.pause(); speechSynthesis.resume(); }, 10000)`, cleared on end.
- Always `speechSynthesis.cancel()` before a new `speak()`.
- The `end` event does not fire if the utterance was cancelled — resolve on `end` **and** `error`, never leave the promise hanging.

### `speech.js`
```js
export function startListening({onInterim, onFinal, onError})
export function stopListening()
export function isListening()
```
- Feature-detect `window.SpeechRecognition || window.webkitSpeechRecognition`. Chrome and Edge only expose the prefixed form.
- `continuous = true`, `interimResults = true`, `lang = "en-US"`.
- **`onend` fires unpredictably, including on brief silence.** Keep an explicit `wantListening` flag and restart inside `onend` only while it is true. Never restart from `onerror`.
- **`error === "no-speech"` or `"aborted"` is normal.** Do not play the error tone or announce a failure. Only `"not-allowed"`, `"service-not-allowed"`, `"audio-capture"` and `"network"` are real errors.
- `.start()` while already started throws `InvalidStateError`. Guard on `isListening()`.
- **The microphone must be stopped before the app speaks, and restarted only after the TTS promise resolves.** Otherwise the app transcribes its own readback and loops forever. Enforce this in `app.js`, not by hoping.

### `index.html`
Controls, in DOM order, all real `<button>`s: mic toggle (`aria-pressed`, label switches
between "Start listening" and "Stop listening"), "Read it back again", "Send", "Cancel",
"Help". One `<h1>`, a `<main>` landmark, and a labelled rate slider (0.75–1.5).
Keyboard: `Space` toggles the mic when focused; `Escape` cancels and stops speech from anywhere.

### `api.js`
Every function returns an object; none throws. On network failure return
`{ok: false, speech: "I couldn't reach the server, so nothing was sent."}` so `app.js` has
exactly one path.

---

# PART V — BUILD PHASES

Each phase ends in something runnable. **Do not proceed past a failing gate.**

### Phase 0 — Skeleton (~30 min)
Create the tree, `requirements.txt`, `.env.example`, `.gitignore`, `pytest.ini`,
`config.py`, `models.py`, and a `main.py` that mounts routers and serves `frontend/` at `/`.

**Ordering rule — the static mount must come last**, after `include_router`, or it swallows the API routes:
```python
app.include_router(voice.router, prefix="/api")
app.include_router(draft.router, prefix="/api")
app.include_router(mail.router,  prefix="/api")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
```

**Gate:** `uvicorn backend.main:app` starts; `GET /api/health` returns `{"status":"ok","fake_ai":true,"fake_gmail":true}`.

---

### Phase 1 — Offline end to end (2–3 h) → F32, F37, F48, F49
`session.py`, `commands.py`, `speechify.py`, `errors.py`, `routes/voice.py`, and the **fake**
paths of `ai/` and `gmail/`. No Ollama, no Google — nothing installed beyond pip packages.

**Gate:**
```bash
curl -X POST localhost:8000/api/turn -H 'content-type: application/json' \
  -d '{"session_id":"t1","transcript":"tell john I will be late"}'
```
returns a `TurnResponse` whose `speech` is a full readback; a follow-up turn with `"send"`
returns a spoken confirmation and appends a line to `outbox.jsonl`.

---

### Phase 2 — Voice frontend (3–4 h) → F6, F7, F8, F10, F23, F24, F25, F26, F46, F50
All six frontend modules plus `index.html` and `styles.css`.

**Gate:** speak "tell John I'll be late" into the browser → hear the full readback → say
"send" → hear the confirmation. **Complete the entire flow with the screen switched off and
the mouse untouched.**

---

### Phase 3 — Language processing (4–5 h) → F1–F5, F17–F21, F27, F31
Build `ai/provider.py` first (§19a), then `prompts.py`, `schemas.py`, `compose`, `edit`,
`mode_detect`. Set `FAKE_AI=0` only after `ollama run llama3.2:3b` answers from the terminal.

Also implement rule **A14** in this phase — the frontend must speak an acknowledgement
within 1.5 s of any model call starting. On a CPU machine this is the difference between
"thinking" and "broken".

**Gate:**
- "make it shorter" then "make it more formal" each produce a changed draft that keeps the same recipient and subject, and the readback reflects the change.
- "Undo" restores the previous draft.
- The schema-validation retry path works: force one malformed response and confirm the spoken fallback sentence.
- **Report the measured latency** of a compose call and an edit call, from the provider log.
- `FAKE_AI=1` still runs the full flow.

---

### Phase 4 — Contacts (2 h) → F12–F16, F43
`data/store.py`, `data/contacts.py`, `ai/contacts_nlp.py`, seed data.

**Gate:** "email John" asks *"Which John — Smith, or Carter?"* and accepts either the
surname or "one"/"two". "email my manager" resolves without asking. "email the whole team"
expands to the group.

---

### Phase 5 — Real email sending (2–3 h + provider setup) → F33, F34
`gmail/auth.py`, `gmail/send.py`. Set `FAKE_GMAIL=0`.

Message construction:
```python
from email.message import EmailMessage
import base64

msg = EmailMessage()
msg["To"] = draft.recipient
msg["Subject"] = draft.subject
if draft.cc:
    msg["Cc"] = ", ".join(draft.cc)
msg.set_content(draft.body)          # set_content, not set_payload
raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

payload = {"raw": raw}
if draft.thread_id:
    payload["threadId"] = draft.thread_id   # sibling of raw, NOT nested inside it
service.users().messages().send(userId="me", body=payload).execute()
```
Drafts nest one level deeper — this asymmetry is a common bug:
```python
service.users().drafts().create(userId="me", body={"message": payload}).execute()
```

**Gate:** a real email arrives in a real inbox, and "save as draft" produces a real draft.
Then disconnect the network and confirm the failure is *spoken* correctly. `FAKE_GMAIL=1` still works.

---

### Phase 6 — Reading mail (3 h) → F22, F36, F38–F41
`gmail/inbox.py`, `ai/summarize.py`, inbox commands and `reading_inbox` phase.

Write one helper `_extract_plain_text(payload)` that walks `payload["parts"]` recursively,
prefers `text/plain` over `text/html`, and strips tags with a regex if only HTML exists.

**Gate:** "read my unread mail" lists senders and subjects; "next email", "read sender",
"summarise this one", "archive this" all work; "reply" composes with the original thread as
context and threads correctly in the provider.

---

### Phase 7 — Advanced editing and actions (3 h) → F9, F28, F29, F30, F35
Mid-speech correction, "new paragraph", CC/BCC, attachments, scheduled send.

**Gate:** dictate a message containing "new paragraph" and hear the pause in readback; add a
CC by voice; attach a file by voice; schedule a send and confirm it dispatches.

---

### Phase 8 — Personalisation and accessibility hardening (half a day) → F42–F45, F47
Tone history, frequent phrases, rate persistence. Then the accessibility pass:

- Screen-reader testing with NVDA (Windows) or VoiceOver (macOS, ⌘F5).
- Verify no double announcements, every state change is audible, all controls reachable by Tab, `Escape` always escapes.
- Force **every** row of the error table (§30) and confirm each spoken message is correct and states whether the email was sent.
- Audit every user-facing string against rule A11.
- Confirm the spoken help lists only commands available in the current phase.
- Write `README.md`.

**Gate:** a person who has never seen the app completes a send with the monitor off.

---

### Phase 9 — Stretch, only after Phase 8 is green
F11 (wake word), F51 (spoken PIN). Do one, well, or neither.

---

# PART VI — QUALITY

## 29. Testing

`pytest.ini` — minimal, with **no `env =` block** (that needs the `pytest-env` plugin, deliberately not a dependency):
```ini
[pytest]
testpaths = tests
```

Set the flags in `tests/conftest.py`, **before any `backend` import**:
```python
import os
os.environ["FAKE_AI"] = "1"
os.environ["FAKE_GMAIL"] = "1"
os.environ["DB_PATH"] = ":memory:"
os.environ["OUTBOX_PATH"] = "test_outbox.jsonl"

from backend.config import get_settings      # imported AFTER the env is set
get_settings.cache_clear()
```
Import order matters: `backend.config` calls `load_dotenv()` at import time and
`get_settings` is cached, so importing it first would freeze the wrong settings and the
tests would silently try to reach the real APIs.

Required tests:
- `test_models.py` — the §20 invariants hold for constructed and default objects.
- `test_speechify.py` — email addresses, markdown stripping, paragraph pauses, the 120-word warning.
- `test_commands.py` — every phrase in §22 maps to the right intent; "send" outside `awaiting_confirm` is refused with the correct sentence.
- `test_contacts.py` — "John" returns two candidates and triggers clarification; "John Smith" resolves outright; "my manager" resolves via alias; "the team" expands.
- `test_turn_flow.py` — a full scripted conversation through `TestClient`: compose → read back → "make it shorter" → "undo" → "send" → success. Asserts `speech` is never empty and never contains `{`, `None` or `Traceback`.
- `test_mail_fake.py` — `FAKE_GMAIL` writes a well-formed line to `outbox.jsonl`; a forced failure returns `success=False` with **HTTP 200** and a speakable message.

**No test may make a network call.**

## 30. Error → speech mapping — `backend/errors.py`

Implement `to_spoken(exc) -> str` with this table plus a catch-all.

| Condition | Spoken message |
|---|---|
| No `credentials.json` | "I can't send mail yet because the email credentials file is missing." |
| Invalid or expired token | "My access to your email has expired. Say 'reconnect my email' to sign in again." |
| HTTP 401/403 from provider | "Your email account refused the request. It may not have granted permission to send mail." |
| HTTP 429 or 5xx | "Your email provider is busy right now. Say 'send' once more to try again." |
| Invalid recipient address | "That address doesn't look right, so I haven't sent it. Say 'change recipient' to fix it." |
| Missing model API key | "I can't write the email because the writing assistant isn't set up." |
| Model rate limit | "The writing assistant is busy. Say 'try again' in a moment." |
| Network failure | "I couldn't reach the internet, so nothing was sent. Your draft is safe." |
| Anything else | "Something went wrong and nothing was sent. Your draft is safe. Say 'help' to hear what you can do." |

**Every message states whether the email was sent.** The worst outcome for a blind user is
not knowing whether the mail went out.

## 31. Error traps — read this before debugging anything

| Symptom | Cause | Fix |
|---|---|---|
| Mic never activates, no error | Page opened via `file://` | Serve from `http://localhost:8000` |
| `SpeechRecognition is not defined` | Firefox or Safari | Chrome/Edge only; show and speak the fallback (F50) |
| App transcribes its own voice, loops forever | Mic left open during TTS | Stop recognition before `speak()`, restart after the promise resolves |
| Readback cuts off after ~15 s | Browser utterance limit | Chunk into ≤200-char sentences + pause/resume keepalive |
| Screen reader says everything twice | Two live regions | One `#status`, rule A2 |
| Audio cues silent | AudioContext created before a user gesture | Create it inside the first click handler |
| `.start()` throws `InvalidStateError` | Recognition already running | Guard on `isListening()` |
| Constant error tone while silent | Treating `no-speech`/`aborted` as errors | Ignore those two |
| `/api/*` returns the HTML page | StaticFiles mounted before routers | Mount static last |
| `sqlite3.ProgrammingError: ... same thread` | Default `check_same_thread=True` | `sqlite3.connect(path, check_same_thread=False)` |
| `AttributeError: 'Draft' object has no attribute 'dict'` | Pydantic v1 syntax | `model_dump()` |
| Model returns prose instead of JSON | `format=` not passed, or passed as the string `"json"` instead of the schema dict | Pass `schema_model.model_json_schema()` |
| `ValidationError` on the model's output | Small model drifted from the schema | Retry once with the schema restated in the user message, then `SpokenError` (§19a) |
| First request takes 30 s, later ones are fast | Model cold-loaded from disk | `keep_alive="30m"`; warm it once at startup |
| Every model call times out | Default client timeout too short for CPU inference | `LLM_TIMEOUT_S=120` |
| `ConnectionError` to localhost:11434 | Ollama not running | Start Ollama; the spoken error must say so plainly |
| Drafts are long and rambling | `num_predict` unset and no brevity instruction | Cap `num_predict` **and** state the word target in the prompt |
| Machine swaps or freezes while drafting | Two models pulled, or an 8B model on 8 GB | Keep one 3B model only |
| OAuth `redirect_uri_mismatch` | "Web application" client type | Create a **Desktop app** OAuth client |
| OAuth `access_denied` at consent | Account not added as a test user | Add it under OAuth consent screen → Test users |
| `insufficientPermissions` after a scope change | Stale `token.json` | Delete `token.json` and re-authenticate |
| OAuth flow hangs forever | Port 8080 occupied | Free the port, or change it consistently in both places |
| `file_cache is unavailable` warning spam | Discovery cache | `build(..., cache_discovery=False)` |
| Draft created but `threadId` ignored | `threadId` nested wrongly | `threadId` sits beside `raw`; drafts wrap the whole payload in `{"message": ...}` |
| `TestClient` raises on import | `httpx` missing | It is in `requirements.txt` — install it |
| Event loop stalls under load | Sync SDK calls in `async def` | All handlers are plain `def` |
| Blank spoken message | `message` was `None` or `""` | Contract invariant test + catch-all in `errors.py` |

## 32. Definition of done for any change

1. `pytest -q` passes.
2. `uvicorn backend.main:app --reload` starts with no warnings.
3. `http://localhost:8000` loads and the full flow works with `FAKE_AI=1 FAKE_GMAIL=1`.
4. The change was navigable keyboard-only (Tab / Enter / Space / Escape), no mouse.
5. Any new user-facing string is a complete spoken sentence.

## 33. Demo script — rehearse this exact sequence

1. Open the page. It says: "Ready. Tap the button or press Enter to start listening."
2. Tap. Say: **"Tell John Smith I'll be twenty minutes late to the standup."**
3. It asks: **"Which John — Smith, or Carter?"** Say: **"Smith."**
4. It reads back recipient, subject and body, then "Say send to send it, or tell me what to change."
5. Say: **"Make it more formal."** → it re-reads the revised draft.
6. Say: **"Read the subject again."** → subject only.
7. Say: **"Send."** → "Sent to John Smith."
8. Say: **"Read my unread mail."** → sender and subject of each.
9. Say: **"Summarise this one."**
10. Say: **"Help."** → it lists the commands available right now.

If the network dies, set `FAKE_AI=1 FAKE_GMAIL=1` and the entire demo above still runs locally.

## 33a. Cost

**Every component of this project is free.**

| Component | Cost | Notes |
|---|---|---|
| Ollama + `llama3.2:3b` | Free | Open source, runs locally, no account |
| Web Speech API (in and out) | Free | Built into Chrome and Edge, no key |
| Gmail API | Free | Generous quota; no billing account required |
| FastAPI, Pydantic, SQLite, rapidfuzz, pytest | Free | Open source |
| Google AI Studio (fallback only) | Free tier | Only if `LLM_PROVIDER=gemini` |

**Do not add a component that requires payment.** If a feature appears to need one, say so
and propose a free alternative instead of introducing the cost.

One honest disclosure for the report: in Chrome, the Web Speech API sends audio to Google's
servers for recognition. It is free to use but not local. If full on-device privacy becomes
a requirement, the replacement is Vosk or `faster-whisper` running locally — a Phase 9 change
affecting only `speech.js` and one new backend endpoint. Note this limitation rather than
claiming the system is entirely offline.

## 34. Out of scope

Do not build: user accounts, a database server, Docker, CI pipelines, a mobile app,
real-time streaming STT over websockets, voice biometrics, or any JavaScript framework.

## 35. When something in this spec is wrong

If you hit a genuine conflict — a pinned version that will not resolve, an API that has
changed, a contract that cannot express what a feature needs — **stop, state the conflict
plainly, and propose the smallest change.** Do not silently reshape a contract in §20 and do
not silently relax an accessibility rule in §3.
