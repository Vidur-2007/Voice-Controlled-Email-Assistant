// Speech output. speak() resolves once the FULL text has been spoken,
// chunked into <=200-char sentence pieces to work around Chrome silently
// cutting off long utterances after ~15 seconds — without this, readback
// of a real email body cuts off mid-sentence, which would be the single
// most damaging bug in this app.
//
// Real pitfalls handled here:
//  - getVoices() returns [] on the first call; wait once for
//    'voiceschanged', with a bounded fallback so it can never hang.
//  - Chrome kills long utterances after ~15s -> chunk + queue chunks.
//  - A pause/resume "keepalive" must run while speaking, or some
//    platforms silently stop mid-utterance.
//  - Always cancel() before starting new speech.
//  - The 'end' event does NOT fire for a cancelled utterance, and Chrome
//    fires NO event at all for chunks still queued (not yet started) when
//    cancel() is called — so resolving only on the last chunk's
//    end/error can hang forever. stopSpeaking() force-settles the
//    in-flight promise directly instead of relying on any browser event.

const MAX_CHUNK_LEN = 200;
const KEEPALIVE_MS = 10000;

let currentRate = 1.0;
let cachedVoice = null;
let voicesPromise = null;

let activeSettle = null; // resolve() for the in-flight speak() call, or null
let keepaliveTimer = null;

function clearKeepalive() {
  if (keepaliveTimer) {
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }
}

function startKeepalive() {
  clearKeepalive();
  keepaliveTimer = setInterval(() => {
    try {
      const synth = window.speechSynthesis;
      if (synth && synth.speaking) {
        synth.pause();
        synth.resume();
      }
    } catch {
      /* never let the keepalive itself break anything */
    }
  }, KEEPALIVE_MS);
}

function getVoicesAsync() {
  if (voicesPromise) return voicesPromise;
  voicesPromise = new Promise((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth) {
      resolve([]);
      return;
    }
    const existing = synth.getVoices();
    if (existing && existing.length > 0) {
      resolve(existing);
      return;
    }
    let settled = false;
    const onVoicesChanged = () => {
      if (settled) return;
      settled = true;
      synth.removeEventListener("voiceschanged", onVoicesChanged);
      resolve(synth.getVoices());
    };
    synth.addEventListener("voiceschanged", onVoicesChanged);
    // Bounded fallback — some browsers never fire voiceschanged at all.
    setTimeout(() => {
      if (settled) return;
      settled = true;
      synth.removeEventListener("voiceschanged", onVoicesChanged);
      resolve(synth.getVoices());
    }, 1000);
  });
  return voicesPromise;
}

async function pickVoice() {
  if (cachedVoice) return cachedVoice;
  const voices = await getVoicesAsync();
  cachedVoice =
    voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("en")) || voices[0] || null;
  return cachedVoice;
}

/** Split text into <=maxLen pieces on sentence, then word, boundaries. */
export function chunkText(text, maxLen = MAX_CHUNK_LEN) {
  const clean = (text || "").trim();
  if (!clean) return [];

  const sentences = clean.match(/[^.!?]+[.!?]*(\s+|$)/g) || [clean];
  const chunks = [];
  let current = "";

  for (let sentence of sentences) {
    sentence = sentence.trim();
    if (!sentence) continue;

    if (sentence.length > maxLen) {
      if (current) {
        chunks.push(current);
        current = "";
      }
      // Hard-split an overlong "sentence" on word boundaries.
      let piece = "";
      for (const word of sentence.split(/\s+/)) {
        const candidate = piece ? piece + " " + word : word;
        if (candidate.length > maxLen) {
          if (piece) chunks.push(piece);
          piece = word;
        } else {
          piece = candidate;
        }
      }
      if (piece) chunks.push(piece);
      continue;
    }

    const candidate = current ? current + " " + sentence : sentence;
    if (candidate.length > maxLen) {
      if (current) chunks.push(current);
      current = sentence;
    } else {
      current = candidate;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export function setRate(r) {
  currentRate = Math.min(1.5, Math.max(0.75, r));
}

export function getRate() {
  return currentRate;
}

export function stopSpeaking() {
  clearKeepalive();
  try {
    window.speechSynthesis && window.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
  if (activeSettle) {
    const settle = activeSettle;
    activeSettle = null;
    settle();
  }
}

/** Speak text aloud. Resolves after the full (chunked) text has finished. */
export function speak(text, { rate } = {}) {
  const synth = window.speechSynthesis;
  if (!synth) {
    return Promise.resolve(); // no TTS support — caller should feature-detect
  }

  stopSpeaking(); // cancel + force-settle whatever was speaking before

  const chunks = chunkText(text);
  if (chunks.length === 0) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearKeepalive();
      activeSettle = null;
      resolve();
    };
    activeSettle = finish;

    pickVoice().then((voice) => {
      if (settled) return; // stopSpeaking() ran while we were resolving a voice

      let index = 0;
      const speakNext = () => {
        if (settled) return;
        if (index >= chunks.length) {
          finish();
          return;
        }
        const utter = new SpeechSynthesisUtterance(chunks[index]);
        utter.rate = rate ?? currentRate;
        if (voice) utter.voice = voice;
        index += 1;

        utter.onend = () => speakNext();
        utter.onerror = () => finish();

        synth.speak(utter);
      };

      startKeepalive();
      speakNext();
    });
  });
}
