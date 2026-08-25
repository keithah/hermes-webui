"""Static-analysis tests for the explicit Cmd/Ctrl+K new-chat command."""
from pathlib import Path

BOOT_JS = (Path(__file__).parent.parent / "static" / "boot.js").read_text(encoding="utf-8")


def _ctrl_k_branch_window() -> str:
    idx = BOOT_JS.find("(e.metaKey||e.ctrlKey)&&e.key==='k'")
    assert idx >= 0, "Cmd/Ctrl+K handler not found in boot.js"
    return BOOT_JS[idx:idx + 1500]


class TestIssue5099CtrlKTextInputGuard:
    def test_ctrl_k_recognizes_editable_targets_without_skipping_the_command(self):
        branch = _ctrl_k_branch_window()
        assert "tagName==='INPUT'" in branch
        assert "tagName==='TEXTAREA'" in branch
        assert "isContentEditable" in branch
        assert "if(isText) return" not in branch

    def test_ctrl_k_prevents_default_for_the_new_chat_command(self):
        branch = _ctrl_k_branch_window()
        prevent_idx = branch.find("e.preventDefault()")
        assert prevent_idx >= 0, "Ctrl+K must prevent the browser's default action"

    def test_ctrl_k_guard_matches_ctrl_b_idiom(self):
        ctrl_b_idx = BOOT_JS.find("(e.key==='b'||e.key==='B')")
        assert ctrl_b_idx >= 0, "Ctrl+B handler not found in boot.js"
        ctrl_b_block = BOOT_JS[max(0, ctrl_b_idx - 250):ctrl_b_idx + 300]
        ctrl_k_block = _ctrl_k_branch_window()
        for needle in (
            "const t=e.target",
            "const isText=t&&",
            "tagName==='INPUT'",
            "tagName==='TEXTAREA'",
            "isContentEditable",
        ):
            assert needle in ctrl_b_block, f"Ctrl+B guard missing {needle!r}"
        assert needle in ctrl_k_block, f"Ctrl+K target detection missing {needle!r}"

    def test_ctrl_k_still_creates_new_session_outside_inputs(self):
        branch = _ctrl_k_branch_window()
        assert "newSession()" in branch
        assert "closeMobileSidebar()" in branch
