// The single live region (rule A2) — exactly one aria-live element in the
// whole app. Nothing else may set aria-live. announce() is the ONLY code
// anywhere allowed to write to it.
//
// #status carries brief transitional STATE only ("Listening…", "Thinking…",
// "Speaking…") — never the full spoken content. The actual conversation
// (readback, help, confirmations) is spoken exclusively through tts.js.
// If both wrote the same long sentence, a screen reader (NVDA/VoiceOver)
// would read it at the same moment the app's own TTS voice is speaking it —
// exactly the double-announcement bug rule A13 forbids.

let statusEl = null;
let lastAnnounced = "";

function getStatusEl() {
  if (!statusEl) {
    statusEl = document.getElementById("status");
  }
  return statusEl;
}

export function announce(text) {
  const el = getStatusEl();
  if (!el) return;

  // If the text is identical to what's already there, a screen reader
  // won't re-announce it (no DOM change). Append a zero-width space so it
  // does — the visible text is unaffected.
  const display = text === lastAnnounced ? text + "​" : text;
  el.textContent = display;
  lastAnnounced = text;
}
