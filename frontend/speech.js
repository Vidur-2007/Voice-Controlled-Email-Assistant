// Speech recognition (STT) wrapper.
//
// Owns THREE independent timers — do not confuse them:
//  1. End-of-turn debounce (~700ms) — fires once finalBuffer has content
//     and no further result arrives. Chrome finalizes an isFinal result
//     on any ~1-1.5s pause even with continuous=true, so a user thinking
//     mid-sentence ("tell John... I'll be late") can produce two separate
//     final results. Accumulating final fragments and only calling
//     onFinal() once this debounce elapses with no further speech is
//     what actually makes a natural pause "not end the turn" (F8), rather
//     than submitting a half turn.
//  2. Interim-only fallback (~1.6s, capped at 3 words) — a real, observed
//     Chrome quirk: a short single-word utterance ("one", "two", a
//     surname) is sometimes NEVER marked isFinal at all — it just sits as
//     an unconfirmed interim guess forever, since Chrome keeps waiting to
//     see if more words are coming. Without this, finalBuffer never gets
//     anything and the mic listens forever with the answer already
//     spoken but never submitted. Scoped to short interim text only (not
//     a blanket fallback) so a genuinely longer utterance that simply
//     hasn't been finalized yet — mid-sentence, still speaking — is never
//     cut off early; only Chrome's own isFinal drives longer utterances.
//  3. F10 silence-stop timer (disabled unless a positive silenceStopMs is
//     passed in) — a much longer "give up entirely" timer, reset only on
//     interim results per spec wording. Firing it stops listening and
//     calls onAutoStop() (not onFinal) — a distinct outcome from a normal
//     turn ending.
//
// onend fires unpredictably, including on brief silence — an explicit
// wantListening flag guards restarts, and restarts NEVER originate from
// onerror. Each call to startListening() builds a brand new recognition
// instance; every handler ignores events from a since-replaced instance
// so a slow-to-fire event from an old session can never corrupt a new one.

const END_OF_TURN_DEBOUNCE_MS = 700;
const INTERIM_FALLBACK_MS = 1600;
const INTERIM_FALLBACK_MAX_WORDS = 3;

function getRecognitionCtor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function isSupported() {
  return !!getRecognitionCtor();
}

let recognition = null;
let wantListening = false;
let active = false; // recognition engine actually running right now

let finalBuffer = "";
let lastInterimText = "";
// F54/§11.1 heuristic 1: did the recogniser revise a word between the
// last interim result and the final one? Captured the instant a result
// in THIS event is final, against whatever interim text the PRIOR event
// left behind — lastInterimText itself gets overwritten below on every
// event, so this has to be read before that happens.
let hadInterimChange = false;
let debounceTimer = null;
let interimFallbackTimer = null;
let silenceTimer = null;
let silenceStopMs = 0;

let callbacks = {
  onInterim: () => {},
  onFinal: () => {},
  onError: () => {},
  onAutoStop: () => {},
};

export function isListening() {
  return active;
}

function clearDebounce() {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
}

function clearInterimFallback() {
  if (interimFallbackTimer) {
    clearTimeout(interimFallbackTimer);
    interimFallbackTimer = null;
  }
}

function clearSilenceTimer() {
  if (silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
  }
}

function clearAllTimers() {
  clearDebounce();
  clearInterimFallback();
  clearSilenceTimer();
}

function stopEngine() {
  active = false;
  clearAllTimers();
  if (recognition) {
    try {
      recognition.stop();
    } catch {
      /* ignore */
    }
  }
}

function flushTurn() {
  clearDebounce();
  clearInterimFallback();
  // Prefer a real final result; fall back to the last stable interim if
  // Chrome never finalized anything at all (the short-utterance quirk).
  const text = finalBuffer.trim() || lastInterimText.trim();
  const changed = hadInterimChange;
  finalBuffer = "";
  lastInterimText = "";
  hadInterimChange = false;
  if (text) {
    wantListening = false; // this listening session is done
    stopEngine();
    callbacks.onFinal(text, changed);
  }
}

function buildRecognition() {
  const Ctor = getRecognitionCtor();
  const rec = new Ctor();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-US";

  // Guards against a stale event firing after this instance has been
  // superseded by a newer startListening() call.
  const isCurrent = () => rec === recognition;

  rec.onstart = () => {
    if (!isCurrent()) return;
    active = true;
  };

  rec.onresult = (event) => {
    if (!isCurrent()) return;

    let interimText = "";
    let finalizedThisEvent = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      const transcript = result[0] ? result[0].transcript : "";
      if (result.isFinal) {
        finalBuffer = (finalBuffer + " " + transcript).trim();
        finalizedThisEvent = (finalizedThisEvent + " " + transcript).trim();
      } else {
        interimText += transcript;
      }
    }

    if (finalizedThisEvent) {
      const priorInterim = lastInterimText.trim();
      if (priorInterim && priorInterim !== finalizedThisEvent) {
        hadInterimChange = true;
      }
    }
    lastInterimText = interimText;
    callbacks.onInterim((finalBuffer + " " + interimText).trim());

    clearDebounce();
    clearInterimFallback();

    if (finalBuffer) {
      debounceTimer = setTimeout(flushTurn, END_OF_TURN_DEBOUNCE_MS);
    } else {
      const interimWordCount = interimText.trim() ? interimText.trim().split(/\s+/).length : 0;
      if (interimWordCount > 0 && interimWordCount <= INTERIM_FALLBACK_MAX_WORDS) {
        interimFallbackTimer = setTimeout(flushTurn, INTERIM_FALLBACK_MS);
      }
    }

    if (silenceStopMs > 0) {
      clearSilenceTimer();
      silenceTimer = setTimeout(() => {
        if (!isCurrent()) return;
        clearDebounce();
        clearInterimFallback();
        finalBuffer = "";
        lastInterimText = "";
        hadInterimChange = false;
        wantListening = false;
        stopEngine();
        callbacks.onAutoStop();
      }, silenceStopMs);
    }
  };

  rec.onerror = (event) => {
    if (!isCurrent()) return;
    const type = event.error;
    if (type === "no-speech" || type === "aborted") {
      return; // normal — never an error tone or a spoken failure
    }
    // not-allowed, service-not-allowed, audio-capture, network: real errors.
    // `active = false` here too, not just in onend — onend is a separate
    // browser-dispatched event with no guaranteed-synchronous timing
    // relative to onerror, and callbacks.onError() below (Phase 9) may
    // synchronously check isListening() to decide whether to re-arm the
    // wake word; it must see the engine as already stopped, not stale.
    active = false;
    wantListening = false;
    clearAllTimers();
    finalBuffer = "";
    lastInterimText = "";
    hadInterimChange = false;
    callbacks.onError({ type });
  };

  rec.onend = () => {
    if (!isCurrent()) return;
    active = false;
    // Restart ONLY while we still want to be listening. Restarts never
    // originate from onerror — only from here.
    if (wantListening) {
      try {
        rec.start();
      } catch {
        wantListening = false;
      }
    }
  };

  return rec;
}

export function startListening({ onInterim, onFinal, onError, onAutoStop, silenceStopMs: sMs } = {}) {
  if (!isSupported()) {
    (onError || (() => {}))({ type: "unsupported" });
    return;
  }

  const nextCallbacks = {
    onInterim: onInterim || (() => {}),
    onFinal: onFinal || (() => {}),
    onError: onError || (() => {}),
    onAutoStop: onAutoStop || (() => {}),
  };

  if (isListening()) {
    // Phase 9 (wake word): retarget an already-running session instead of
    // no-op'ing. Without this, a real mic tap while a passive wake-word
    // session is listening would leave the engine running but still
    // reporting to the OLD (wake-word) callbacks — the user's next words
    // would silently get discarded as "not the wake phrase" instead of
    // reaching the real turn they just asked to start. Restarting
    // `recognition.start()` here instead would risk InvalidStateError and
    // a real audio glitch; the engine itself doesn't need to change, only
    // who's listening for its next result.
    callbacks = nextCallbacks;
    silenceStopMs = sMs || 0;
    finalBuffer = "";
    lastInterimText = "";
    hadInterimChange = false;
    clearAllTimers();
    return;
  }

  callbacks = nextCallbacks;
  silenceStopMs = sMs || 0;
  finalBuffer = "";
  lastInterimText = "";
  hadInterimChange = false;

  recognition = buildRecognition();
  wantListening = true;
  try {
    recognition.start();
  } catch {
    wantListening = false;
  }
}

export function stopListening() {
  wantListening = false;
  // A manual stop with unflushed speech still processes it — the user
  // saying "that's it" by tapping should behave like finishing a turn,
  // not silently discarding what was already captured. Checks the
  // interim text too, not just finalBuffer, for the same reason flushTurn
  // does (a short utterance may never have been marked final at all).
  if (finalBuffer.trim() || lastInterimText.trim()) {
    flushTurn();
    return;
  }
  clearAllTimers();
  stopEngine();
}
