"""A8 regression test (PHASE_10_PLUS_SPEC.md §10.1) — every CSS transition
or animation declaration must live inside
`@media (prefers-reduced-motion: no-preference)`. No CSS-media-query test
harness exists in this project (and isn't worth building for one rule), so
this checks the raw stylesheet text directly: strip out `@keyframes`
blocks (they define what an animation looks like, not that it's used
unconditionally) and the properly-gated media block itself, then assert
nothing naming `transition:`/`animation:` is left in what remains.
"""

import re
from pathlib import Path

STYLES_PATH = Path(__file__).resolve().parent.parent / "frontend" / "styles.css"


def _extract_balanced_block(text: str, open_brace_index: int) -> int:
    """Returns the index just past the `}` that balances the `{` at
    open_brace_index.
    """
    depth = 0
    for i in range(open_brace_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise AssertionError("unbalanced braces in styles.css")


def _strip_blocks(text: str, selector_pattern: str) -> str:
    out = []
    pos = 0
    for m in re.finditer(selector_pattern, text):
        if m.start() < pos:
            continue  # already consumed by a previous block's removal
        out.append(text[pos : m.start()])
        brace_index = text.index("{", m.end())
        pos = _extract_balanced_block(text, brace_index)
    out.append(text[pos:])
    return "".join(out)


def test_a8_no_motion_outside_reduced_motion_guard():
    css = STYLES_PATH.read_text(encoding="utf-8")
    remaining = _strip_blocks(css, r"@keyframes\s+[\w-]+\s*")
    remaining = _strip_blocks(remaining, r"@media\s*\(\s*prefers-reduced-motion\s*:\s*no-preference\s*\)\s*")
    leftover = re.findall(r"\b(?:transition|animation)\s*:", remaining)
    assert leftover == []
