"""UI 1-3 (sticky room, preview dock, live board): static layout checks.

These are frontend-only changes, so the tests assert structure, not
backend behaviour: the canvas card sticks, the preview dock and live
board exist in the left column, every preview path mirrors into the
dock, the live board renders from shownStates() (so a Time Machine
past view shows recorded states, never live state leaking in), and
Reset/decline hide the dock.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class UILayoutTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "frontend" / "index.html").read_text()
        self.css = (ROOT / "frontend" / "app.css").read_text()
        self.js = (ROOT / "frontend" / "app.js").read_text()

    def test_sticky_room(self):
        self.assertIn(".canvas-card { position: sticky;", self.css)
        self.assertIn(".layout { align-items: start; }", self.css)
        # Narrow single-column layout must un-stick, or the card would
        # eat a phone screen.
        self.assertRegex(self.css, r"@media \(max-width: 60rem\) \{[^}]*\.canvas-card \{ position: static;")

    def test_preview_dock_and_live_board_in_canvas_card(self):
        canvas_start = self.html.find('<section class="canvas-card">')
        aside_start = self.html.find('<aside class="panel">')
        canvas = self.html[canvas_start:aside_start]
        self.assertIn('id="preview-dock"', canvas)
        self.assertIn('id="preview-dock-img"', canvas)
        self.assertIn('id="live-board"', canvas)
        self.assertIn('id="live-devices"', canvas)
        self.assertIn('id="live-automations"', canvas)
        # Live board is read-only, so it must NOT be guest-hidden.
        board = canvas[canvas.find('id="live-board"') - 100:canvas.find('id="live-board"')]
        self.assertNotIn("guest-hide", board)

    def test_all_preview_paths_mirror_into_dock(self):
        for label in ("move", "advisor", "time-of-day"):
            pass
        self.assertIn('showPreview(b2.preview_url, "Illustrative move preview")', self.js)
        self.assertIn('showPreview(b2.preview_url, "Illustrative advisor preview")', self.js)
        self.assertIn('showPreview(body.preview_url, `${body.label} illustrative preview`)', self.js)
        # Dock is a mirror only: no second apply path is created in it.
        dock_js = self.js[self.js.find("function showPreview"):self.js.find("function renderLiveBoard")]
        self.assertNotIn("advisor/apply", dock_js)
        self.assertNotIn("move-approve", dock_js)

    def test_live_board_uses_shown_states_not_raw_states(self):
        board_js = self.js[self.js.find("function renderLiveBoard"):self.js.find("function renderLiveBoard") + 2000]
        self.assertIn("shownStates()", board_js)
        self.assertNotIn("for (const [id, st] of states)", board_js)

    def test_reset_and_decline_hide_dock(self):
        self.assertGreaterEqual(self.js.count("hidePreview();"), 2)


if __name__ == "__main__":
    unittest.main()
