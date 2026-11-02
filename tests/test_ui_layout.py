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

    def test_photo_first_layout(self):
        # Photo-first supersedes the sticky side column: hero on top,
        # panel as a grid of cards below it, bottom sheet on narrow.
        self.assertIn(".layout {\n  display: block;", self.css)
        self.assertIn(".panel {\n  display: grid;", self.css)
        self.assertNotIn(".canvas-card { position: sticky;", self.css)
        self.assertIn('id="panel-toggle"', self.html)
        narrow = self.css[self.css.find("@media (max-width: 60rem) {"):]
        self.assertIn(".panel {\n    position: fixed;", narrow)

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
        self.assertIn('showPreview(b2.preview_url, "Illustrative move preview", `Move ${prettyOid(body.object_id)}`)', self.js)
        self.assertIn('showPreview(b2.preview_url, "Illustrative advisor preview", setting.name)', self.js)
        self.assertIn('showPreview(body.preview_url, `${body.label} illustrative preview`, body.label)', self.js)
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


class UIFixesTest(unittest.TestCase):
    """Fixes for the UI audit: past-view leaks, board filtering, dots,
    stale previews, dock provenance, and the sticky overflow."""

    def setUp(self):
        self.html = (ROOT / "frontend" / "index.html").read_text()
        self.css = (ROOT / "frontend" / "app.css").read_text()
        self.js = (ROOT / "frontend" / "app.js").read_text()

    def test_shown_states_past_only_not_merged_live(self):
        fn = self.js[self.js.find("function shownStates"):self.js.find("function updateSteps")]
        self.assertIn("return new Map(pastView);", fn)
        self.assertNotIn("new Map(states)", fn)

    def test_stamps_live_only_in_devices_and_board(self):
        self.assertIn("const showLast = !timeTravel && last;", self.js)
        self.assertIn("const lt = timeTravel ? null", self.js)
        self.assertIn("fired.hidden = true;", self.js)
        # No "never fired" in a past view: board builds the suffix only live.
        board = self.js[self.js.find("function renderLiveBoard"):self.js.find("function renderLiveBoard") + 2500]
        self.assertIn('timeTravel ? ""', board)

    def test_board_whitelists_devices_no_sensors(self):
        board = self.js[self.js.find("function renderLiveBoard"):self.js.find("function renderLiveBoard") + 2500]
        self.assertIn("isBoardDevice", board)
        self.assertIn('id.startsWith("light.")', board)
        self.assertIn('id.startsWith("binary_sensor.")', board)

    def test_automation_dot_has_size_and_colour(self):
        self.assertIn("#live-automations .dot { width: 0.6rem;", self.css)
        self.assertIn("#live-automations .dot.on { background: var(--accent);", self.css)

    def test_stale_preview_hidden_on_photo_suggest_apply_and_past(self):
        self.assertIn("async function usePhoto(body) {\n  hidePreview();", self.js)
        self.assertGreaterEqual(self.js.count("hidePreview();"), 8)

    def test_dock_has_provenance_label(self):
        self.assertIn('id="preview-dock-label"', self.html)
        self.assertIn("function showPreview(src, alt, label)", self.js)
        self.assertIn("Preview — ${label}", self.js)

    def test_dock_and_board_collapsible_with_capped_heights(self):
        self.assertIn('<details id="preview-dock"', self.html)
        self.assertIn('<details id="live-board" open>', self.html)
        self.assertIn("#preview-dock img { max-height: 40vh;", self.css)
        self.assertIn("#live-devices, #live-automations { max-height: 35vh;", self.css)


class UITestPassFixesTest(unittest.TestCase):
    """Fixes for the Nov 2 live test pass: stale last-fired, Rearrange
    decline dock, Reset residuals, and the Minute 00 picker."""

    def setUp(self):
        self.js = (ROOT / "frontend" / "app.js").read_text()
        self.py = (ROOT / "backend" / "app.py").read_text()

    def test_rearrange_decline_closes_dock(self):
        decline = self.js[self.js.find('textContent = "Decline";'):]
        self.assertIn("hidePreview();", decline[:500])

    def test_reset_restores_model_delay_and_tm_error(self):
        reset = self.js[self.js.find('getElementById("reset-btn").addEventListener'):]
        self.assertIn('auto-provider', reset)
        self.assertIn('value = "hosted"', reset)
        self.assertIn('auto-delay', reset)
        self.assertIn('tm-view', reset)
        self.assertIn('innerHTML = "";', reset)

    def test_stale_last_triggered_suppressed(self):
        self.assertIn("def _stale_last_triggered", self.py)
        self.assertIn("_stale_last_triggered(p.get(\"created\"), stamp)", self.py)
        self.assertIn("_stale_last_triggered(created_by_id[cfg_id]", self.py)
class UIModernTest(unittest.TestCase):
    """Photo-first modernizations: automation cards, Time Machine
    scrubber, bottom sheet. The judge tour is documented only (see
    README test below) — no judge mode is built."""

    def setUp(self):
        self.html = (ROOT / "frontend" / "index.html").read_text()
        self.css = (ROOT / "frontend" / "app.css").read_text()
        self.js = (ROOT / "frontend" / "app.js").read_text()
        self.readme = (ROOT / "README.md").read_text()

    def test_automation_cards_replace_selector(self):
        self.assertIn('id="automation-cards"', self.html)
        self.assertNotIn('id="whatif-proposal"', self.html)
        self.assertNotIn('id="whatif-btn"', self.html)
        self.assertIn("auto-card", self.js)
        self.assertIn('"Run What-If"', self.js)
        self.assertIn("/api/automations/${p.id}", self.js)
        # Cards carry trigger, condition, delay and last-fired.
        self.assertIn("last fired", self.js)

    def test_time_machine_scrubber_replaces_selects(self):
        self.assertIn('id="tm-range"', self.html)
        self.assertIn('id="tm-play-btn"', self.html)
        self.assertNotIn('id="tm-date"', self.html)
        self.assertNotIn('id="tm-hour"', self.html)
        self.assertNotIn('id="tm-min"', self.html)
        self.assertIn("/api/snapshot-times", self.js)
        self.assertIn("no snapshots yet", self.js)
        self.assertIn("tmPlaying", self.js)

    def test_tour_documented_as_future_onboarding_only(self):
        self.assertIn("Onboarding tour (future, NOT a judge mode)", self.readme)
        self.assertIn("when user accounts and account management exist", self.readme)
        self.assertNotIn("judge tour", self.js.lower())
