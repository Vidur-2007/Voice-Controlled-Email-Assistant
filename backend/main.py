"""FastAPI app: routers, static mount, health, scheduler.

Ordering rule (do not change): the static mount comes LAST, after every
include_router call, or it swallows the /api/* routes.
"""

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.gmail.schedule import run_due_scheduled_sends
from backend.routes import voice, draft, mail, metrics, prefs

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# F35: the background dispatcher for scheduled sends. A plain daemon
# thread, not a new dependency (apscheduler isn't in requirements.txt and
# nothing like it exists in this codebase) — all the real logic lives in
# the directly-testable run_due_scheduled_sends(); this loop is
# deliberately thin. Note: TestClient(app), used WITHOUT `with` (exactly
# as tests/conftest.py's `client` fixture does), never triggers `lifespan`
# — confirmed against starlette's own source — so this thread never runs
# under pytest, and run_due_scheduled_sends() must stay independently
# callable for tests to exercise it directly.
_stop_event = threading.Event()


def _scheduler_loop() -> None:
    settings = get_settings()
    while not _stop_event.is_set():
        try:
            run_due_scheduled_sends()
        except Exception:  # noqa: BLE001 - one bad poll must never kill the loop
            pass
        _stop_event.wait(settings.scheduler_poll_s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _stop_event.clear()
    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    yield
    _stop_event.set()


app = FastAPI(title="Voice Email Assistant", lifespan=lifespan)


@app.get("/api/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "fake_ai": settings.fake_ai,
        "fake_gmail": settings.fake_gmail,
        "has_gmail_token": Path(settings.gmail_token_path).exists(),
        "silence_stop_ms": settings.silence_stop_ms,
    }


app.include_router(voice.router, prefix="/api")
app.include_router(draft.router, prefix="/api")
app.include_router(mail.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(prefs.router, prefix="/api")

# Static mount MUST be last — see ordering rule above.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
