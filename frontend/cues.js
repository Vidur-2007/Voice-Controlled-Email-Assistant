// Distinct audio cue per EVENT TYPE, not per state (rule A3): a failure
// must be identifiable by ear alone, without parsing a sentence.
//   start beep    — 880 Hz, short          — listening has begun
//   stop beep     — 660 Hz, short          — listening has stopped
//   error tone    — 220 Hz, longer, lower  — something genuinely went wrong
//   working chime — 520/660 Hz two-blip    — a slow operation is still running (A14)
//   wake chime    — 740 Hz quick two-blip  — the wake phrase was heard (Phase 9, F11)
//
// The AudioContext MUST be created inside a user-gesture handler, not at
// module load — otherwise the browser suspends it and every cue is
// silently silent with no error at all. primeAudio() must be the first
// line of the mic button's click handler.

let audioCtx = null;

export function primeAudio() {
  if (audioCtx) {
    if (audioCtx.state === "suspended") {
      audioCtx.resume().catch(() => {});
    }
    return;
  }
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return; // no WebAudio support — cues just silently no-op
  try {
    audioCtx = new Ctx();
  } catch {
    audioCtx = null;
  }
}

function tone(freqHz, durationMs, gainPeak = 0.18) {
  if (!audioCtx) return; // never primed (e.g. mic unsupported) — no-op safely
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.value = freqHz;

    const now = audioCtx.currentTime;
    const durationSec = durationMs / 1000;
    // Short fade in/out avoids an audible click at start/stop.
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(gainPeak, now + 0.015);
    gain.gain.setValueAtTime(gainPeak, now + durationSec - 0.03);
    gain.gain.linearRampToValueAtTime(0, now + durationSec);

    osc.connect(gain).connect(audioCtx.destination);
    osc.start(now);
    osc.stop(now + durationSec);
  } catch {
    // Never let a cue failure break the conversation flow.
  }
}

export function playStart() {
  tone(880, 150);
}

export function playStop() {
  tone(660, 150);
}

export function playError() {
  // Longer and lower, per spec — must be identifiable by ear alone.
  tone(220, 450, 0.22);
}

export function playWake() {
  // Phase 9 (F11) — a new, distinct event type (A3: "the app heard its
  // wake phrase" is not the same event as "listening has begun", so it
  // doesn't reuse playStart()). Quicker and higher than the working
  // chime (90ms apart vs. 130ms, 740 Hz vs. 520/660) so the two are never
  // confused by ear even though both are two-blip patterns.
  tone(740, 80, 0.16);
  setTimeout(() => tone(740, 80, 0.16), 90);
}

function playWorking() {
  // A two-blip chime, audibly distinct from start/stop/error — rule A14's
  // "distinct working tone" for anything slower than 1.5s (real AI calls).
  // Never speaks the acknowledgment via TTS: doing so risks a screen
  // reader announcing the live-region state text at the same moment the
  // app's own voice says something too (rule A13's double-announcement
  // bug) — this tone is a second, independent audio channel instead.
  tone(520, 90, 0.15);
  setTimeout(() => tone(660, 90, 0.15), 130);
}

let workingLoopTimer = null;

export function startWorkingLoop(intervalMs = 5000) {
  stopWorkingLoop();
  playWorking(); // first chime right away
  workingLoopTimer = setInterval(playWorking, intervalMs);
}

export function stopWorkingLoop() {
  if (workingLoopTimer) {
    clearInterval(workingLoopTimer);
    workingLoopTimer = null;
  }
}
