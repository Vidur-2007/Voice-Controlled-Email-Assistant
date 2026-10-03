"""Offline tests for backend/attachments.py (F30). No network calls."""

from pathlib import Path

from backend import attachments


def test_save_attachment_writes_file_and_returns_full_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.attachments.get_settings",
        lambda: type("S", (), {"attachments_dir": str(tmp_path)})(),
    )
    path = attachments.save_attachment("sess-1", "invoice.pdf", b"hello")
    assert Path(path).exists()
    assert Path(path).read_bytes() == b"hello"
    assert Path(path).name == "invoice.pdf"
    assert "sess-1" in path


def test_save_attachment_strips_directory_components(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.attachments.get_settings",
        lambda: type("S", (), {"attachments_dir": str(tmp_path)})(),
    )
    path = attachments.save_attachment("sess-2", "../../evil.txt", b"x")
    assert Path(path).name == "evil.txt"
    # Never escapes its own session directory.
    assert Path(path).parent == tmp_path / "sess-2"


def test_get_last_attachment_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.attachments.get_settings",
        lambda: type("S", (), {"attachments_dir": str(tmp_path)})(),
    )
    assert attachments.get_last_attachment("sess-3") == ""
    path = attachments.save_attachment("sess-3", "a.txt", b"a")
    assert attachments.get_last_attachment("sess-3") == path


def test_get_last_attachment_empty_if_file_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.attachments.get_settings",
        lambda: type("S", (), {"attachments_dir": str(tmp_path)})(),
    )
    path = attachments.save_attachment("sess-4", "a.txt", b"a")
    Path(path).unlink()
    assert attachments.get_last_attachment("sess-4") == ""


def test_set_last_attachment_overrides():
    attachments.set_last_attachment("sess-5", "/some/path.txt")
    assert attachments._last_attachment["sess-5"] == "/some/path.txt"
