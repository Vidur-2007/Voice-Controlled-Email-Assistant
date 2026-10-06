// The client state machine — ties every other module together.
//
// CRITICAL RULE, enforced here (not hoped for): the microphone is always
// stopped BEFORE the app speaks, and only reopened AFTER the speech
// promise resolves. Every path that leads to tts.speak() — a normal turn,
// an error, F10's auto-stop message — goes through stop-then-speak, never
// speak-while-listening. Otherwise the app transcribes its own voice and
// loops forever.
//
// Phase 9 (F11, wake word) raised the stakes on this rule: setState("idle")
// can now itself reopen the mic (for passive wake-word listening, via the
// centralized hook in setState() below), so it's no longer just a cosmetic
// button-text update — every path that both speaks AND settles to "idle"
// must call setState("idle") AFTER its tts.speak() resolves, never before
// (see handleSttError()/handleAutoStop()/onWakeWordToggle() for the pattern).
//
// Turn-taking is hands-free after the first tap: TurnResponse.listen_again
// tells us to reopen the mic right after speaking each response, so a
// whole conversation (readback -> "send" -> confirmation) needs only the
// one initial tap. A second tap, or Escape, stops that loop.
//
// A "generation" counter guards against races from barge-in: tapping the
// mic or pressing Escape while a turn is in flight (processing or
// speaking) invalidates that turn, so its eventual response can never
// clobber the state the user has already moved on to.

import * as a11y from "./a11y.js";
import * as api from "./api.js";
import * as cues from "./cues.js";
import * as speech from "./speech.js";
import * as tts from "./tts.js";

let sessionId = "";
let state = "idle"; // 'idle' | 'listening' | 'processing' | 'speaking'
let conversationActive = false;
let turnGeneration = 0;
let silenceStopMs = 0;
let sttSupported = true;
let ttsSupported = true;

// Phase 9 (F11, stretch) — opt-in, off by default. Deliberately NOT a 5th
// value on `state`: wake-mode is an orthogonal flag layered on top of the
// existing idle/listening/processing/speaking machinery, armed only while
// state is genuinely "idle" (see maybeArmWakeWord()), so none of the
// existing turnGeneration/conversationActive race-guard logic for a real
// turn needs to change.
let wakeWordEnabled = false;
const WAKE_PHRASE = "hey ultron";
const WAKE_WORD_ON_MESSAGE =
  "Wake word on. From now on, say 'hey ultron' anytime to start talking, even without " +
  "tapping the button — your microphone will stay on and keep listening for that phrase " +
  "while the app is otherwise idle, and what it hears gets sent to your browser's speech " +
  "service the same way it already does when you're actively using the app. Say 'hey " +
  "ultron' on its own to start listening, or say 'hey ultron' followed by what you want " +
  "to do. Tap this button again to turn it off.";
const WAKE_WORD_OFF_MESSAGE = "Wake word off. Your microphone only listens when you tap the button.";

let els = {};

function newSessionId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return "sess-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

function logTurn(who, text) {
  if (!els.transcriptList || !text) return;
  const li = document.createElement("li");
  li.className = who === "you" ? "log-you" : "log-assistant";
  li.textContent = (who === "you" ? "You: " : "Assistant: ") + text;
  els.transcriptList.appendChild(li);
  els.transcriptList.scrollTop = els.transcriptList.scrollHeight;
}

function updateMicButton() {
  const btn = els.mic;
  if (!btn) return;
  if (!sttSupported) {
    btn.disabled = true;
    btn.textContent = "Voice input not supported in this browser";
    btn.setAttribute("aria-pressed", "false");
    return;
  }
  const listening = state === "listening";
  btn.setAttribute("aria-pressed", listening ? "true" : "false");
  btn.textContent = listening ? "Stop listening" : "Start listening";
  btn.setAttribute("data-state", state);
}

function setState(next) {
  state = next;
  updateMicButton();
  // Centralized, not sprinkled at every call site — every place that
  // settles into "idle" (end of a turn, Escape, an STT error, auto-stop,
  // a finished attachment upload, a manual stop with nothing said) should
  // resume passive wake-word listening the same way, and a single hook
  // here can't be missed the way scattering the call across every site
  // that calls setState("idle") could be.
  if (next === "idle") maybeArmWakeWord();
}

function maybeArmWakeWord() {
  if (wakeWordEnabled && state === "idle" && !speech.isListening()) {
    beginWakeListening();
  }
}

function beginWakeListening() {
  // Silent arm — no start cue, no "Listening…" announcement. This re-arms
  // every time the engine naturally restarts (Chrome's continuous mode
  // still finalizes on pauses), so cueing every cycle would be constant
  // noise; the only audible moment is actual detection, in
  // handleWakeWordTranscript() below.
  speech.startListening({
    onInterim: () => {},
    onFinal: handleWakeWordTranscript,
    onError: handleSttError,
    onAutoStop: () => {},
    silenceStopMs: 0,
  });
}

function handleWakeWordTranscript(text) {
  if (!wakeWordEnabled) return; // turned off mid-utterance — see onWakeWordToggle()

  const low = text.toLowerCase();
  const idx = low.indexOf(WAKE_PHRASE);
  if (idx === -1) {
    // Ambient speech, not the wake phrase — total silence: no cue, no
    // announcement, no transcript entry, nothing sent anywhere. Just
    // re-arm and keep waiting.
    beginWakeListening();
    return;
  }

  cues.playWake();
  a11y.announce("Heard you.");

  const remainder = (text.slice(0, idx) + text.slice(idx + WAKE_PHRASE.length)).trim();
  if (remainder) {
    // One breath ("hey ultron tell John I'll be late") — skip straight to
    // a real turn, exactly as if the user had already tapped and spoken.
    logTurn("you", remainder);
    conversationActive = true;
    runTurn(remainder);
  } else {
    // The phrase alone — behave exactly like a mic tap.
    conversationActive = true;
    beginListening();
  }
}

function updateWakeWordButton() {
  const btn = els.wakeWordBtn;
  if (!btn) return;
  btn.setAttribute("aria-pressed", wakeWordEnabled ? "true" : "false");
  btn.textContent = wakeWordEnabled ? "Disable wake word" : "Enable wake word";
}

async function onWakeWordToggle() {
  cues.primeAudio();
  // Same interrupt discipline as every other button (submitCommand()) —
  // tapping this is a barge-in if a real turn happens to be mid-flight,
  // not just a background flag flip: speaking the (long, first-time-on)
  // disclosure while the mic is still actively capturing a real command
  // would double up two things talking into/out of the same audio path.
  turnGeneration += 1;
  const myGeneration = turnGeneration;

  // Flip the flag BEFORE stopping anything: speech.stopListening() below
  // can synchronously flush a partial, mid-utterance wake-mode buffer
  // straight through handleWakeWordTranscript() (its existing callback
  // target) — that function's own "already disabled?" guard must see the
  // NEW value at that exact synchronous moment, or disabling while
  // mid-utterance would silently re-arm itself right back on.
  wakeWordEnabled = !wakeWordEnabled;
  updateWakeWordButton();

  speech.stopListening();
  tts.stopSpeaking();
  cues.stopWorkingLoop();

  // Set state directly, NOT via setState("idle") — that would trigger the
  // centralized maybeArmWakeWord() hook and reopen the mic BEFORE the
  // disclosure below is spoken, violating the one rule every other path
  // in this file follows: the mic stays closed until speech finishes, or
  // the app risks hearing (and misreading) its own voice.
  state = "idle";
  updateMicButton();

  if (wakeWordEnabled) {
    a11y.announce("Wake word on.");
    logTurn("assistant", WAKE_WORD_ON_MESSAGE);
    if (ttsSupported) await tts.speak(WAKE_WORD_ON_MESSAGE);
  } else {
    a11y.announce("Wake word off.");
    logTurn("assistant", WAKE_WORD_OFF_MESSAGE);
    if (ttsSupported) await tts.speak(WAKE_WORD_OFF_MESSAGE);
  }
  if (myGeneration !== turnGeneration) return; // superseded while speaking

  maybeArmWakeWord();
}

function beginListening() {
  setState("listening");
  cues.playStart();
  a11y.announce("Listening…");
  speech.startListening({
    onInterim: () => {}, // not surfaced anywhere — avoids live-region spam (A2)
    onFinal: handleFinalTranscript,
    onError: handleSttError,
    onAutoStop: handleAutoStop,
    silenceStopMs,
  });
}

function handleFinalTranscript(text, hadInterimChange) {
  logTurn("you", text);
  runTurn(text, hadInterimChange);
}

function submitCommand(phrase) {
  cues.primeAudio();
  // A click interrupts whatever's happening, same as a mic-button barge-in.
  turnGeneration += 1;
  speech.stopListening();
  tts.stopSpeaking();
  logTurn("you", phrase);
  runTurn(phrase);
}

async function runTurn(transcriptText, hadInterimChange = null) {
  turnGeneration += 1;
  const myGeneration = turnGeneration;

  if (speech.isListening()) speech.stopListening();
  cues.playStop();
  setState("processing");
  a11y.announce("Thinking…");

  // A14: anything slower than 1.5s must be audibly acknowledged. Text via
  // the live region (screen-reader users) plus a distinct working tone
  // (cues.js) — never via TTS, which would risk a screen reader announcing
  // the live region at the same moment the app's own voice speaks too
  // (the double-announcement bug rule A13 forbids).
  const ackTimer = setTimeout(() => {
    a11y.announce("Writing that now…");
    cues.startWorkingLoop();
  }, 1500);

  const response = await api.postTurn(sessionId, transcriptText, hadInterimChange);
  clearTimeout(ackTimer);
  cues.stopWorkingLoop();
  if (myGeneration !== turnGeneration) return; // superseded by a barge-in/Escape

  logTurn("assistant", response.speech);
  if (!response.ok) cues.playError();

  setState("speaking");
  a11y.announce("Speaking…");
  await tts.speak(response.speech);
  if (myGeneration !== turnGeneration) return; // superseded while speaking

  // F30: point focus at a control (currently only "attach-btn") AFTER
  // speech finishes, never during — a screen reader announcing the newly
  // focused element mid-utterance would double up with the app's own
  // voice (rule A13). .focus() itself needs no user-activation, unlike
  // .click(), so this is always safe to call here.
  if (response.focus_target) {
    const target = document.getElementById(response.focus_target);
    if (target) target.focus();
  }

  if (response.listen_again && conversationActive) {
    beginListening();
  } else {
    conversationActive = false;
    setState("idle");
    a11y.announce("Ready.");
  }
}

// F30: a File object can never flow through a speech transcript, so this
// is a separate path from runTurn() — same stop-listening-before-speaking
// discipline, same A14 working-tone acknowledgement, just triggered by a
// file input's change event instead of a spoken turn.
async function handleFileSelected(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = ""; // allow re-selecting the same file again later
  if (!file) return;

  turnGeneration += 1; // invalidate any turn still in flight, same as a barge-in
  speech.stopListening();
  tts.stopSpeaking();
  cues.stopWorkingLoop();

  setState("processing");
  a11y.announce("Attaching…");

  const ackTimer = setTimeout(() => {
    a11y.announce("Attaching that now…");
    cues.startWorkingLoop();
  }, 1500);

  const result = await api.uploadAttachment(sessionId, file);
  clearTimeout(ackTimer);
  cues.stopWorkingLoop();

  logTurn("assistant", result.message);
  if (!result.success) cues.playError();

  setState("speaking");
  a11y.announce("Speaking…");
  await tts.speak(result.message);

  if (conversationActive) {
    beginListening();
  } else {
    setState("idle");
    a11y.announce("Ready.");
  }
}

const STT_ERROR_MESSAGES = {
  "not-allowed": "Microphone access was denied. Please allow microphone access and try again.",
  "service-not-allowed": "Microphone access was denied. Please allow microphone access and try again.",
  "audio-capture": "I can't find a microphone. Please check your microphone and try again.",
  network: "I couldn't reach the speech recognition service. Please check your connection.",
  unsupported: "Voice input isn't supported in this browser. Please use Chrome or Edge.",
};

function handleSttError({ type }) {
  turnGeneration += 1;
  conversationActive = false;
  cues.playError();
  a11y.announce("Error.");
  const message = STT_ERROR_MESSAGES[type] || "Something went wrong with listening. Please try again.";
  // setState("idle") moved to AFTER speaking (was before) — Phase 9: that
  // call now has a real side effect (it can reopen the mic for passive
  // wake-word listening via the centralized hook), not just a cosmetic
  // button-text update, so it must wait until the error message has
  // actually finished, same as the top-of-file "mic closed until speech
  // finishes" rule every other path here already follows.
  if (ttsSupported) {
    tts.speak(message).then(() => setState("idle"));
  } else {
    setState("idle");
  }
}

async function handleAutoStop() {
  // F10 — disabled by default (silenceStopMs=0); only reachable if enabled.
  cues.playStop();
  a11y.announce("Paused.");
  await tts.speak("I stopped listening because it went quiet. Say 'keep going' to add more.");
  // setState("idle") moved to AFTER speaking — same Phase 9 reasoning as
  // handleSttError() above.
  setState("idle");
  if (conversationActive) beginListening();
}

function onMicToggle() {
  cues.primeAudio();

  if (state === "idle") {
    conversationActive = true;
    beginListening();
    return;
  }

  if (state === "listening") {
    conversationActive = false;
    speech.stopListening(); // may synchronously flush -> runTurn, moving state to 'processing'
    if (state === "listening") {
      setState("idle");
      a11y.announce("Stopped listening.");
    }
    return;
  }

  // processing or speaking: tapping barges in.
  turnGeneration += 1; // invalidate whatever turn is currently in flight
  tts.stopSpeaking();
  cues.stopWorkingLoop(); // a stale slow request's A14 tone must not keep looping
  speech.stopListening();
  conversationActive = true;
  beginListening();
}

function onEscape() {
  // A local, immediate stop — cuts off audio I/O from any state without
  // touching the server-side draft (that's what the Cancel button/command
  // is for). "Escape always escapes."
  turnGeneration += 1;
  tts.stopSpeaking();
  cues.stopWorkingLoop();
  speech.stopListening();
  conversationActive = false;
  setState("idle");
  a11y.announce("Stopped.");
}

function onKeydown(event) {
  if (event.key === "Escape") onEscape();
}

function wireRateSlider() {
  if (!els.rate) return;
  // "input" fires continuously while dragging — live preview only, no
  // network call per pixel of drag. "change" fires once on release — that
  // one persists via setPrefs (F45). Both update tts.setRate()/the label;
  // only "change" also saves.
  els.rate.addEventListener("input", () => {
    const value = parseFloat(els.rate.value);
    tts.setRate(value);
    if (els.rateValue) els.rateValue.textContent = value.toFixed(2) + "x";
  });
  els.rate.addEventListener("change", () => {
    api.setPrefs(parseFloat(els.rate.value));
  });
}

async function init() {
  sessionId = newSessionId();

  els = {
    mic: document.getElementById("mic-btn"),
    readback: document.getElementById("readback-btn"),
    send: document.getElementById("send-btn"),
    cancel: document.getElementById("cancel-btn"),
    help: document.getElementById("help-btn"),
    attachBtn: document.getElementById("attach-btn"),
    fileInput: document.getElementById("file-input"),
    wakeWordBtn: document.getElementById("wake-word-btn"),
    rate: document.getElementById("rate-slider"),
    rateValue: document.getElementById("rate-value"),
    transcriptList: document.getElementById("transcript-list"),
  };

  sttSupported = speech.isSupported();
  ttsSupported = !!window.speechSynthesis;

  if (els.mic) els.mic.addEventListener("click", onMicToggle);
  if (els.readback) els.readback.addEventListener("click", () => submitCommand("read it back"));
  if (els.send) els.send.addEventListener("click", () => submitCommand("send"));
  if (els.cancel) els.cancel.addEventListener("click", () => submitCommand("cancel"));
  if (els.help) els.help.addEventListener("click", () => submitCommand("help"));
  if (els.attachBtn && els.fileInput) {
    // A direct, synchronous click handler — the only reliable way to open
    // a real OS file picker (see the F30 comment on #attach-btn in
    // index.html). cues.primeAudio() first, same as submitCommand(), since
    // this may be the very first user gesture on the page.
    els.attachBtn.addEventListener("click", () => {
      cues.primeAudio();
      els.fileInput.click();
    });
    els.fileInput.addEventListener("change", handleFileSelected);
  }
  if (els.wakeWordBtn) els.wakeWordBtn.addEventListener("click", onWakeWordToggle);
  document.addEventListener("keydown", onKeydown);
  wireRateSlider();

  const health = await api.getHealth();
  silenceStopMs = (health && health.silence_stop_ms) || 0;

  // F45: apply the saved rate before anything speaks, so even the very
  // first "Ready." utterance uses it, not a one-utterance-late correction.
  const prefs = await api.getPrefs();
  if (prefs && typeof prefs.speech_rate === "number") {
    tts.setRate(prefs.speech_rate);
    if (els.rate) els.rate.value = String(prefs.speech_rate);
    if (els.rateValue) els.rateValue.textContent = prefs.speech_rate.toFixed(2) + "x";
  }

  updateMicButton();

  if (!sttSupported) {
    a11y.announce("Voice input not supported.");
    if (ttsSupported) {
      tts.speak(
        "Voice input isn't supported in this browser. Please use Chrome or Edge. " +
          "You can still use the Read it back, Send, Cancel, and Help buttons."
      );
    }
    return;
  }

  a11y.announce("Ready.");
  if (ttsSupported) {
    // May silently no-op before any user gesture (browser autoplay policy)
    // — harmless, the first tap is the qualifying gesture that unblocks
    // audio/speech reliably from then on.
    tts.speak("Ready. Tap the button or press Enter to start listening.");
  }
}

document.addEventListener("DOMContentLoaded", init);
