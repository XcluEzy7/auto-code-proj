"""Reusable Textual widgets for ACAP TUI."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ProgressBar, Static


class ArcadeProgress(Vertical):
    """Retro-styled progress display with an animated status line."""

    PHRASES = [
        "Compiling intent",
        "Forging prompts",
        "Calibrating stack",
        "Priming handoff",
    ]

    def compose(self) -> ComposeResult:
        yield Static("[queued]", id="arcade-status")
        yield ProgressBar(total=100, show_eta=False, id="arcade-bar")

    def set_progress(self, value: int) -> None:
        bar = self.query_one("#arcade-bar", ProgressBar)
        bar.progress = max(0, min(value, 100))

    def set_status(self, text: str) -> None:
        self.query_one("#arcade-status", Static).update(text)

    def pulse_phrase(self, tick: int) -> None:
        phrase = self.PHRASES[tick % len(self.PHRASES)]
        self.set_status(f"[running] {phrase}")
