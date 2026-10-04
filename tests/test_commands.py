import pytest

from backend.commands import help_speech, match_bcc_trigger, match_cc_trigger, match_schedule_trigger, parse_command


@pytest.mark.parametrize(
    "phrase", ["send", "Send", "  send  ", "send it", "send it now", "yes send", "go ahead and send"]
)
def test_send_phrases(phrase):
    assert parse_command(phrase) == "SEND"


@pytest.mark.parametrize("phrase", ["cancel", "never mind", "forget it", "discard"])
def test_cancel_phrases(phrase):
    assert parse_command(phrase) == "CANCEL"


@pytest.mark.parametrize("phrase", ["help", "what can i say", "what are my options"])
def test_help_phrases(phrase):
    assert parse_command(phrase) == "HELP"


@pytest.mark.parametrize("phrase", ["start over", "scrap that", "start again"])
def test_restart_phrases(phrase):
    assert parse_command(phrase) == "RESTART"


@pytest.mark.parametrize("phrase", ["repeat that", "say that again", "read it again", "read it back"])
def test_repeat_phrases(phrase):
    assert parse_command(phrase) == "REPEAT"


@pytest.mark.parametrize("phrase", ["read the subject", "what's the subject", "whats the subject"])
def test_read_subject_phrases(phrase):
    assert parse_command(phrase) == "READ_SUBJECT"


@pytest.mark.parametrize("phrase", ["read the body", "read the message"])
def test_read_body_phrases(phrase):
    assert parse_command(phrase) == "READ_BODY"


@pytest.mark.parametrize("phrase", ["who is it going to", "read the recipient"])
def test_read_recipient_phrases(phrase):
    assert parse_command(phrase) == "READ_RECIPIENT"


@pytest.mark.parametrize("phrase", ["undo", "undo that"])
def test_undo_phrases(phrase):
    assert parse_command(phrase) == "UNDO"


@pytest.mark.parametrize("phrase", ["redo", "redo that"])
def test_redo_phrases(phrase):
    assert parse_command(phrase) == "REDO"


def test_tone_formal_phrase():
    assert parse_command("make it formal") == "TONE_FORMAL"


def test_tone_friendly_phrase():
    assert parse_command("make it friendly") == "TONE_FRIENDLY"


def test_tone_firm_phrase():
    assert parse_command("make it firm") == "TONE_FIRM"


@pytest.mark.parametrize("phrase", ["make it more polite", "make it apologetic"])
def test_tone_apologetic_phrases(phrase):
    # §22's table and F20's own phrase list word this one intent slightly
    # differently — both phrasings are accepted.
    assert parse_command(phrase) == "TONE_APOLOGETIC"


@pytest.mark.parametrize("phrase", ["make it shorter", "keep it short"])
def test_shorter_phrases(phrase):
    assert parse_command(phrase) == "SHORTER"


def test_longer_phrase():
    assert parse_command("add more detail") == "LONGER"


def test_unmatched_transcript_returns_none():
    assert parse_command("tell john I will be late") is None
    assert parse_command("") is None


def test_command_is_not_matched_as_substring():
    # "cancel" appearing inside a longer sentence must NOT trigger CANCEL.
    assert parse_command("I'll cancel my subscription later") is None


def test_help_speech_varies_by_phase():
    idle_help = help_speech("idle")
    confirm_help = help_speech("awaiting_confirm")
    assert idle_help != confirm_help
    assert "send" in confirm_help.lower()


def test_send_refused_outside_awaiting_confirm(client):
    resp = client.post("/api/turn", json={"session_id": "cmd-1", "transcript": "send"})
    body = resp.json()
    assert body["speech"] == "I haven't read the message back to you yet. Say 'read it back' first."
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# Phase 7: ADD_CC, NEW_PARAGRAPH, ATTACH, ATTACH_LAST, SCHEDULE
# ---------------------------------------------------------------------------


def test_add_cc_bare_phrase():
    assert parse_command("add cc") == "ADD_CC"


def test_new_paragraph_phrase():
    assert parse_command("new paragraph") == "NEW_PARAGRAPH"


@pytest.mark.parametrize("phrase", ["attach a file", "attach a document"])
def test_attach_phrases(phrase):
    assert parse_command(phrase) == "ATTACH"


@pytest.mark.parametrize("phrase", ["attach the last document i mentioned", "attach that again"])
def test_attach_last_phrases(phrase):
    assert parse_command(phrase) == "ATTACH_LAST"


def test_help_speech_has_awaiting_schedule_time_branch():
    speech = help_speech("awaiting_schedule_time")
    assert "time" in speech.lower()
    assert speech != help_speech("idle")


@pytest.mark.parametrize(
    ("transcript", "expected_hint"),
    [
        ("add cc Sarah", "Sarah"),
        ("copy in Sarah", "Sarah"),
        ("cc Sarah", "Sarah"),
        ("copy Sarah", "Sarah"),
    ],
)
def test_match_cc_trigger_extracts_hint(transcript, expected_hint):
    assert match_cc_trigger(transcript) == expected_hint


def test_match_cc_trigger_bare_add_cc_returns_none():
    # No name attached -> not a trigger match; "add cc" alone is _PHRASES' job.
    assert match_cc_trigger("add cc") is None


def test_match_cc_trigger_no_match_returns_none():
    assert match_cc_trigger("tell John I will be late") is None


@pytest.mark.parametrize(
    ("transcript", "expected_phrase"),
    [
        ("send this at 5pm", "5pm"),
        ("send this for tomorrow at 9am", "tomorrow at 9am"),
        ("schedule this for 5pm", "5pm"),
        ("schedule this at 5pm", "5pm"),
    ],
)
def test_match_schedule_trigger_extracts_phrase(transcript, expected_phrase):
    assert match_schedule_trigger(transcript) == expected_phrase


# ---------------------------------------------------------------------------
# Completeness pass: ADD_BCC, KEEP_GOING, REPLY_ALL, FORWARD
# ---------------------------------------------------------------------------


def test_add_bcc_bare_phrase():
    assert parse_command("add bcc") == "ADD_BCC"


def test_keep_going_phrase():
    assert parse_command("keep going") == "KEEP_GOING"


@pytest.mark.parametrize("phrase", ["reply all", "reply to everyone", "reply all to this"])
def test_reply_all_phrases(phrase):
    assert parse_command(phrase) == "REPLY_ALL"


@pytest.mark.parametrize("phrase", ["forward this", "forward this email", "forward it"])
def test_forward_phrases(phrase):
    assert parse_command(phrase) == "FORWARD"


@pytest.mark.parametrize(
    ("transcript", "expected_hint"),
    [
        ("add bcc Sarah", "Sarah"),
        ("bcc Sarah", "Sarah"),
    ],
)
def test_match_bcc_trigger_extracts_hint(transcript, expected_hint):
    assert match_bcc_trigger(transcript) == expected_hint


def test_match_bcc_trigger_bare_add_bcc_returns_none():
    assert match_bcc_trigger("add bcc") is None


def test_match_bcc_trigger_no_match_returns_none():
    assert match_bcc_trigger("tell John I will be late") is None


def test_bcc_and_cc_triggers_never_collide():
    # "bcc Sarah" must never be mistaken for a CC trigger, and vice versa.
    assert match_cc_trigger("bcc Sarah") is None
    assert match_bcc_trigger("cc Sarah") is None
    assert match_bcc_trigger("copy in Sarah") is None


def test_match_schedule_trigger_no_match_returns_none():
    assert match_schedule_trigger("send it now") is None
