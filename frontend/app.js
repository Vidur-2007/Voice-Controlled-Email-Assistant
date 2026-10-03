// The client state machine — ties every other module together.
//
// CRITICAL RULE, enforced here (not hoped for): the microphone is always
// stopped BEFORE the app speaks, and only reopened AFTER the speech
// promise resolves. Every path that leads to tts.speak() — a normal turn,
// an error, F10's auto-stop message — goes through stop-then-speak, never
// speak-while-listening. Otherwise the app transcribes its own voice and
// loops forever.
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

function handleFinalTranscript(text) {
  logTurn("you", text);
  runTurn(text);
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

async function runTurn(transcriptText) {
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

  const response = await api.postTurn(sessionId, transcriptText);
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
  setState("idle");
  a11y.announce("Error.");
  const message = STT_ERROR_MESSAGES[type] || "Something went wrong with listening. Please try again.";
  if (ttsSupported) tts.speak(message);
}

async function handleAutoStop() {
  // F10 — disabled by default (silenceStopMs=0); only reachable if enabled.
  cues.playStop();
  setState("idle");
  a11y.announce("Paused.");
  await tts.speak("I stopped listening because it went quiet. Say 'keep going' to add more.");
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
  els.rate.addEventListener("input", () => {
    const value = parseFloat(els.rate.value);
    tts.setRate(value);
    if (els.rateValue) els.rateValue.textContent = value.toFixed(2) + "x";
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
  document.addEventListener("keydown", onKeydown);
  wireRateSlider();

  const health = await api.getHealth();
  silenceStopMs = (health && health.silence_stop_ms) || 0;

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
