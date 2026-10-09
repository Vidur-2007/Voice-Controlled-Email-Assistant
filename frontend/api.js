// Fetch wrappers that NEVER throw — app.js always has exactly one path to
// handle, regardless of success, an HTTP error, or the network being down.

// Bounded so a hung request can't strand the UI — but must comfortably
// exceed the backend's own LLM_TIMEOUT_S (120s default, config.py). A
// real compose/edit call can legitimately take 10-20s+ on CPU inference
// (more on a cold model load), so this must not be shorter than that.
const TIMEOUT_MS = 130000;

function fallbackTurnResponse(speech) {
  return {
    ok: false,
    speech,
    phase: "idle",
    draft: null,
    awaiting_confirmation: false,
    listen_again: true, // keep the conversation loop alive so the user can just try again
    focus_target: null,
  };
}

function fallbackMailResult(message) {
  return { success: false, message };
}

async function getJson(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(path, { signal: controller.signal });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function postJson(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** POST /api/turn. Always resolves with a TurnResponse-shaped object. */
export async function postTurn(sessionId, transcript, hadInterimChange = null, lastInterimTranscript = null) {
  const body = { session_id: sessionId, transcript };
  // Omitted (not just null) for a typed/non-mic turn, so it's never
  // confused with a real "no" answer from live recognition (F54).
  if (hadInterimChange !== null) body.had_interim_change = hadInterimChange;
  // Phase 11 (§11.2a): the raw interim text, for server-side word-level
  // diffing — additive alongside the boolean above, never replacing it.
  if (lastInterimTranscript !== null) body.last_interim_transcript = lastInterimTranscript;
  const data = await postJson("/api/turn", body);
  if (!data) {
    return fallbackTurnResponse("I couldn't reach the server, so nothing was sent.");
  }
  return data;
}

/** GET /api/health. Resolves with the health payload, or null on failure. */
export async function getHealth() {
  return getJson("/api/health");
}

/**
 * GET /api/draft/recoverable (F56). Resolves with {recoverable: false} on
 * failure — a page load must never crash just because this check failed.
 */
export async function getRecoverableDraft() {
  const data = await getJson("/api/draft/recoverable");
  return data || { recoverable: false };
}

/**
 * GET /api/prefs (F45). Resolves with the saved prefs, or a default-rate
 * fallback on failure — the rate slider must still work even if this call
 * fails, just without persistence for that page load.
 */
export async function getPrefs() {
  const data = await getJson("/api/prefs");
  return data || { speech_rate: 1.0 };
}

/** POST /api/prefs (F45). Resolves with the (possibly clamped) saved value. */
export async function setPrefs(speechRate) {
  const data = await postJson("/api/prefs", { speech_rate: speechRate });
  return data || { speech_rate: speechRate };
}

/**
 * POST /api/mail/attachment (F30). A File object can never flow through a
 * speech transcript, so this bypasses /api/turn entirely — always
 * resolves with a MailResult-shaped object, same never-throw contract as
 * postTurn().
 */
export async function uploadAttachment(sessionId, file) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const body = new FormData();
  body.append("session_id", sessionId);
  body.append("file", file);
  try {
    const res = await fetch("/api/mail/attachment", { method: "POST", body, signal: controller.signal });
    if (!res.ok) return fallbackMailResult("I couldn't attach that file.");
    return await res.json();
  } catch {
    return fallbackMailResult("I couldn't reach the server, so the file wasn't attached.");
  } finally {
    clearTimeout(timer);
  }
}
