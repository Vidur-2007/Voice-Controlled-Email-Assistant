"""Direct draft endpoints (dev/testing) — /api/draft/compose, /api/draft/edit.

Completeness pass: this was still the Phase-0 stub despite Phases 0-9
being complete and the underlying compose/edit logic (ai/compose.py,
ai/edit.py) having existed since Phase 3 — §21's route table requires
these two, exposed directly for testing without the frontend/session
machinery, same pattern as routes/mail.py.

Both are stateless: no session_id, no contact/recipient resolution (no
clarifying sub-conversation exists here to have), no undo history. That's
deliberate — those all depend on `ConversationState`, which only
`/api/turn` (routes/voice.py) manages.
"""

from fastapi import APIRouter

from backend.ai.compose import compose_email
from backend.ai.edit import revise
from backend.ai.mode_detect import detect_mode
from backend.models import Draft, DraftComposeRequest, DraftEditRequest

router = APIRouter()


@router.post("/draft/compose", response_model=Draft)
def draft_compose(req: DraftComposeRequest) -> Draft:
    mode = req.mode
    if mode is None:
        # No follow-up turn exists on this stateless endpoint to ask a
        # clarifying "which mode?" question in. detect_mode()'s own
        # ask=True case (only reachable in real-AI mode, the 15-40 word
        # ambiguous zone) already has a precedent for exactly this
        # situation: under FAKE_AI=1 it defaults that same zone to
        # "brief" because there's no model to consult and the offline
        # flow must stay a single round trip. Reuse that same default
        # and reasoning here rather than inventing a new one.
        result = detect_mode(req.transcript)
        mode = result.mode or "brief"
    draft, _recipient_hint = compose_email(req.transcript, mode)
    return draft


@router.post("/draft/edit", response_model=Draft)
def draft_edit(req: DraftEditRequest) -> Draft:
    return revise(req.draft, req.instruction)
