"""F57 — attachment read-aloud (PHASE_10_PLUS_SPEC.md §13.4). Text
extraction only; backend/ai/summarize.py already handles the >300-word
summary-first behavior, applied by the caller (routes/voice.py).
"""

from pathlib import Path

import pypdf
from docx import Document

from backend.errors import SpokenError

# Extension -> a spoken name for the type, used ONLY for the unsupported-
# type message (§13.4's own example: "a spreadsheet"). Not exhaustive —
# anything missing here falls to the generic "that kind of file".
_TYPE_NAMES = {
    ".xlsx": "a spreadsheet",
    ".xls": "a spreadsheet",
    ".csv": "a spreadsheet",
    ".pptx": "a presentation",
    ".ppt": "a presentation",
    ".jpg": "an image",
    ".jpeg": "an image",
    ".png": "an image",
    ".gif": "an image",
    ".zip": "a compressed archive",
}


def _unsupported_message(extension: str) -> str:
    kind = _TYPE_NAMES.get(extension.lower(), "that kind of file")
    return f"That attachment is {kind}, and I can't read it aloud yet."


def _extract_pdf(path: str) -> str:
    reader = pypdf.PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _extract_docx(path: str) -> str:
    document = Document(path)
    paragraphs = [p.text.strip() for p in document.paragraphs]
    return "\n".join(p for p in paragraphs if p)


def extract_text(path: str) -> str:
    """Returns the attachment's plain text. Raises SpokenError, naming
    the type, for anything not PDF/Word/plain text (§13.4).
    """
    extension = Path(path).suffix.lower()
    if extension == ".pdf":
        return _extract_pdf(path)
    if extension == ".docx":
        return _extract_docx(path)
    if extension == ".txt":
        return Path(path).read_text(encoding="utf-8", errors="replace")
    raise SpokenError(_unsupported_message(extension))
