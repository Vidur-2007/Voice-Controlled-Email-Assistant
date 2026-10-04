"""OAuth flow (Phase 5, prerequisite for F33/F34).

Only `InstalledAppFlow.run_local_server()` exists to do this interactively
— `run_console()` (the old copy-paste-a-code flow) was removed entirely
from google-auth-oauthlib, confirmed by reading the installed source, not
assumed from an old tutorial. That means the *first* connection, and any
reconnection, is inherently a sighted, one-time, browser-based step —
there is no way to drive real Google OAuth consent through voice alone.
This module is what `POST /api/mail/auth` calls (a deliberate, separate,
developer-run step — never triggered inline from a voice turn, since it
would block a `/api/turn` request for however long a human takes to click
through a browser window).

Scope is `gmail.compose` (send + drafts, Phase 5) plus `gmail.modify`
(list/read/archive/mark-read, Phase 6 — confirmed against the installed
Gmail API discovery doc that `messages().modify()` specifically requires
`gmail.modify`; `gmail.compose` does not cover it). Keeping both rather
than trying to consolidate to one is deliberate: `gmail.modify` is a
strict superset for everything this app does, but there's no downside to
listing both explicitly.

Adding a scope here does NOT, by itself, invalidate an old token.json —
traced through the installed google-auth source: `Credentials.valid` is
just `token is not None and not expired`; it never checks scope. Loading
an old, compose-only token would report itself "valid" and only fail with
a confusing real 403 on the first call that actually needs the new scope.
`get_credentials()` below checks the *raw* scopes stored in token.json
before trusting it, and falls through to a fresh interactive flow itself
if they don't cover what SCOPES currently requires.
"""

from pathlib import Path
from typing import Optional

import json

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from backend.config import get_settings
from backend.errors import SpokenError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Phase 8 accessibility audit: this is the message a real user actually
# hears for the "no credentials.json" §30 row — raised directly as a
# SpokenError, which bypasses errors.py's _PATTERNS table entirely
# (to_spoken() returns a SpokenError's own .message verbatim). Tightened
# with the same explicit "so nothing was sent" clause as errors.py's copy.
_NO_CREDENTIALS_FILE_MESSAGE = (
    "I can't send mail yet because the email credentials file is missing, so nothing was sent."
)


def _credentials_path() -> Path:
    return Path(get_settings().gmail_credentials_path)


def _token_path() -> Path:
    return Path(get_settings().gmail_token_path)


def _save_token(creds: Credentials) -> None:
    _token_path().write_text(creds.to_json(), encoding="utf-8")


def _run_interactive_flow() -> Credentials:
    """Opens a real browser window for the user to sign in and grant
    access. Blocks until they finish. Only ever called from `connect()`
    (the dedicated /api/mail/auth endpoint) or as get_credentials()'s
    last resort — never from inside a voice turn.
    """
    if not _credentials_path().exists():
        raise SpokenError(_NO_CREDENTIALS_FILE_MESSAGE)

    flow = InstalledAppFlow.from_client_secrets_file(str(_credentials_path()), SCOPES)
    creds = flow.run_local_server(port=0)  # port=0 -> OS picks a free port, no "8080 occupied" trap
    _save_token(creds)
    return creds


def _token_has_required_scopes(token_path: Path) -> bool:
    """Read the RAW scopes stored in token.json (not what Credentials.
    from_authorized_user_file reconstructs, since that trusts whatever
    SCOPES the caller passes in rather than what was actually granted).
    """
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    granted = set(data.get("scopes", []))
    return set(SCOPES).issubset(granted)


def get_credentials() -> Credentials:
    """Used by send_email()/save_draft()/inbox functions: return a usable
    Credentials object. Loads token.json if present AND it actually
    covers the currently-required scopes, silently refreshes an expired
    one, and falls back to the interactive flow if there's no usable
    token yet (missing, insufficient scope, or an unrefreshable expiry).
    """
    token_path = _token_path()
    creds: Optional[Credentials] = None

    if token_path.exists() and _token_has_required_scopes(token_path):
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except RefreshError:
            pass  # fall through to a fresh interactive flow

    return _run_interactive_flow()


def connect() -> None:
    """POST /api/mail/auth: always forces a fresh consent flow, discarding
    any existing token — a locally-unexpired token can still have been
    revoked server-side, so re-running the real flow is the only way to
    know for sure. Serves both first-time setup and "reconnect my email."
    """
    token_path = _token_path()
    if token_path.exists():
        token_path.unlink()
    _run_interactive_flow()


def get_my_email() -> str:
    """F36 (reply-all): the authenticated account's own address, so it can
    be excluded from a reply-all's CC list. Calls Gmail's getProfile() —
    confirmed against the installed Gmail API discovery doc that this
    requires only the gmail.modify scope already granted since Phase 6, so
    adding this needs NO scope bump and NO forced reconnect (unlike the
    gmail.modify scope-bump episode Phase 6 actually had to handle).
    """
    from googleapiclient.discovery import build  # local import: avoids a

    # module-load-time dependency on googleapiclient for callers that only
    # need get_credentials()/connect() (e.g. routes/mail.py's /mail/auth).
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]
