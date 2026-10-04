"""Speech-rate persistence — /api/prefs (F45).

No route for this existed before Phase 8, and none of localStorage/
sessionStorage is used anywhere in this app (same reasoning as session_id:
deliberately avoided). F45 says "remember... across sessions," and §27's
storage rule is "stdlib sqlite3 only" — so this is the same kind of
necessary route addition Phase 6 (inbox) and Phase 7 (schedule/attachment)
already made beyond the original §21 table.

Global, not per-session: this is a single-user app.
"""

from fastapi import APIRouter

from backend.data.prefs import get_pref, set_pref
from backend.models import Prefs

router = APIRouter()

_RATE_KEY = "speech_rate"
_RATE_MIN = 0.75
_RATE_MAX = 1.5
_RATE_DEFAULT = 1.0


@router.get("/prefs", response_model=Prefs)
def get_prefs() -> Prefs:
    raw = get_pref(_RATE_KEY)
    rate = float(raw) if raw is not None else _RATE_DEFAULT
    return Prefs(speech_rate=rate)


@router.post("/prefs", response_model=Prefs)
def set_prefs(prefs: Prefs) -> Prefs:
    # Clamped server-side, not just trusted from the client — matches the
    # slider's own min/max in index.html, defensively enforced here too.
    clamped = max(_RATE_MIN, min(_RATE_MAX, prefs.speech_rate))
    set_pref(_RATE_KEY, str(clamped))
    return Prefs(speech_rate=clamped)
