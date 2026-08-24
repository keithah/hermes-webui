"""Regression tests for Cmd/Ctrl+N and Cmd/Ctrl+T new-chat shortcuts."""

from pathlib import Path


BOOT_JS = (Path(__file__).parent.parent / "static" / "boot.js").read_text(encoding="utf-8")
SHORTCUT = "(e.metaKey||e.ctrlKey)&&(e.key==='n'||e.key==='N'||e.key==='t'||e.key==='T')"


def _block_from(start: int) -> str:
    depth = 0
    for end in range(start, len(BOOT_JS)):
        char = BOOT_JS[end]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return BOOT_JS[start : end + 1]
    raise AssertionError("new-chat shortcut block not closed")


def test_cmd_ctrl_n_and_t_use_the_existing_safe_new_chat_flow():
    """Cmd/Ctrl+N/T must not create duplicate idle sessions or interrupt streams."""
    assert SHORTCUT in BOOT_JS
    branch = _block_from(BOOT_JS.index(SHORTCUT))

    assert "if(isText) return;" in branch
    assert "e.preventDefault();" in branch
    assert "_currentSessionIsReusableEmptyChat()" in branch
    assert "await newSession();await renderSessionList();closeMobileSidebar();$('msg').focus();" in branch
