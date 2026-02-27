#!/usr/bin/env python3
"""Textual TUI for ACAP prompt generation + configure + handoff."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual import work
from textual.widgets import Footer, Header, Input, RichLog, Static

from config import get_config
from configure import run_configure
from prompter import run_analysis_session, run_generation_session, write_prompt_files
from provider_cli import provider_default_model
from tui_models import PromptFlowPhase
from tui_services import build_handoff_command, compute_flow_completion, default_project_dir
from tui_widgets import ArcadeProgress


class AcapTuiApp(App[list[str] | None]):
    """Interactive prep assistant with keyboard-first flow."""

    CSS = """
    Screen {
      layout: vertical;
    }
    #main {
      height: 1fr;
    }
    #left {
      width: 36;
      border: round #6cc;
      padding: 1;
    }
    #right {
      border: round #9f6;
      padding: 1;
    }
    #menu {
      height: 8;
      margin-bottom: 1;
    }
    #timeline {
      height: 10;
      margin-bottom: 1;
    }
    #status {
      height: 4;
      margin-bottom: 1;
    }
    #req_input {
      height: 8;
      margin-bottom: 1;
    }
    #logs.hidden {
      display: none;
    }
    #milestone {
      color: yellow;
      height: 2;
    }
    """

    BINDINGS = [
        Binding("up", "menu_up", "Up", priority=True),
        Binding("down", "menu_down", "Down", priority=True),
        Binding("enter", "menu_select", "Select", priority=True),
        Binding("e", "toggle_edit_mode", "Edit Fields", priority=True),
        Binding("l", "toggle_logs", "Toggle Logs"),
        Binding("h", "handoff", "Handoff"),
        Binding("q", "quit", "Quit"),
    ]

    MENU_ITEMS = [
        "Start End-to-End Prep",
        "Prompt Wizard Only",
        "Configure Only",
        "Quit",
    ]

    selected_index = reactive(0)
    pulse_tick = reactive(0)

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.args = args
        self.cfg = get_config()
        self.flow_mode: str | None = None
        self.handoff_command: list[str] | None = None
        self.edit_mode: bool = False
        self.phase_state: dict[PromptFlowPhase, str] = {
            PromptFlowPhase.ANALYZE: "queued",
            PromptFlowPhase.QA: "queued",
            PromptFlowPhase.GENERATE: "queued",
            PromptFlowPhase.WRITE: "queued",
            PromptFlowPhase.CONFIGURE: "queued",
            PromptFlowPhase.HANDOFF: "queued",
        }

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static(id="menu")
                yield Static(id="timeline")
                yield ArcadeProgress(id="arcade")
                yield Static("", id="milestone")
            with Vertical(id="right"):
                yield Static(
                    "Menu mode: arrows + Enter. Press E to edit fields, L for logs.",
                    id="status",
                )
                yield Input(
                    value=" ".join(self.args.prompt_files or []),
                    placeholder="Prompt source files (space separated)",
                    id="prompt_files",
                )
                yield Input(
                    value=str(self.args.project_dir),
                    placeholder="Project dir",
                    id="project_dir",
                )
                yield Input(
                    value=self.args.agent_cli or self.cfg.agent_cli_id,
                    placeholder="Provider: claude|codex|omp|opencode",
                    id="provider_id",
                )
                default_model = self.args.model or provider_default_model(
                    self.args.agent_cli or self.cfg.agent_cli_id,
                    self.cfg,
                )
                yield Input(
                    value=default_model,
                    placeholder="Model",
                    id="model_id",
                )
                yield Input(
                    placeholder="Paste requirements text here (optional; file input wins)",
                    id="req_input",
                )
                log = RichLog(id="logs")
                log.add_class("hidden")
                yield log
        yield Footer()

    def on_mount(self) -> None:
        self._render_menu()
        self._render_timeline()
        self._set_inputs_enabled(False)
        self.set_interval(0.7, self._pulse_arcade)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for widget_id in ("#prompt_files", "#project_dir", "#provider_id", "#model_id", "#req_input"):
            input_widget = self.query_one(widget_id, Input)
            input_widget.disabled = not enabled
        if enabled:
            self.set_focus(self.query_one("#prompt_files", Input))
        else:
            self.set_focus(None)

    def _pulse_arcade(self) -> None:
        self.pulse_tick += 1
        self.query_one("#arcade", ArcadeProgress).pulse_phrase(self.pulse_tick)

    def _render_menu(self) -> None:
        lines: list[str] = ["[b]ACAP PREP TUI[/b]\n"]
        for idx, item in enumerate(self.MENU_ITEMS):
            marker = ">" if idx == self.selected_index else " "
            lines.append(f"{marker} {item}")
        self.query_one("#menu", Static).update("\n".join(lines))

    def _render_timeline(self) -> None:
        lines = ["[b]Phases[/b]"]
        for phase in PromptFlowPhase:
            state = self.phase_state[phase]
            lines.append(f"{phase.value.upper():<10} {state}")
        self.query_one("#timeline", Static).update("\n".join(lines))

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _append_log(self, line: str) -> None:
        self.query_one("#logs", RichLog).write(line)

    def _set_phase(self, phase: PromptFlowPhase, state: str, message: str = "") -> None:
        self.phase_state[phase] = state
        self._render_timeline()
        progress = compute_flow_completion(phase)
        self.query_one("#arcade", ArcadeProgress).set_progress(progress)
        if message:
            self._set_status(message)
        if state == "done":
            self.query_one("#milestone", Static).update(f"Milestone unlocked: {phase.value}")

    def _stream_cb(self, stream: str, text: str) -> None:
        self.call_from_thread(self._append_log, f"[{stream}] {text}")

    def _status_cb(self, phase_name: str, message: str) -> None:
        mapping = {
            "analyze": PromptFlowPhase.ANALYZE,
            "generate": PromptFlowPhase.GENERATE,
            "write": PromptFlowPhase.WRITE,
            "configure": PromptFlowPhase.CONFIGURE,
        }
        phase = mapping.get(phase_name)
        if phase is not None:
            self.call_from_thread(self._set_phase, phase, "running", message)

    def action_menu_up(self) -> None:
        self.selected_index = (self.selected_index - 1) % len(self.MENU_ITEMS)
        self._render_menu()

    def action_menu_down(self) -> None:
        self.selected_index = (self.selected_index + 1) % len(self.MENU_ITEMS)
        self._render_menu()

    def action_menu_select(self) -> None:
        if self.edit_mode:
            self._set_status("Exit edit mode with E before selecting a menu action")
            return
        choice = self.MENU_ITEMS[self.selected_index]
        if choice == "Quit":
            self.exit(None)
            return
        if choice == "Start End-to-End Prep":
            self.flow_mode = "end_to_end"
            self.run_flow_worker(include_configure=True)
            return
        if choice == "Prompt Wizard Only":
            self.flow_mode = "prompt_only"
            self.run_flow_worker(include_configure=False)
            return
        if choice == "Configure Only":
            self.flow_mode = "configure_only"
            self.run_configure_worker()

    def action_toggle_logs(self) -> None:
        log = self.query_one("#logs", RichLog)
        if log.has_class("hidden"):
            log.remove_class("hidden")
            self._set_status("Stream view enabled")
        else:
            log.add_class("hidden")
            self._set_status("Phase view enabled")

    def action_handoff(self) -> None:
        if not self.handoff_command:
            self._set_status("Handoff not ready yet")
            return
        self.exit(self.handoff_command)

    def action_toggle_edit_mode(self) -> None:
        self.edit_mode = not self.edit_mode
        self._set_inputs_enabled(self.edit_mode)
        if self.edit_mode:
            self._set_status("Edit mode enabled: type in fields. Press E to return to menu mode.")
        else:
            self._set_status("Menu mode enabled: use arrows + Enter to select workflow.")

    def _resolve_inputs(self) -> tuple[list[str], str, str, str, Path]:
        file_input = self.query_one("#prompt_files", Input).value.strip()
        prompt_files = file_input.split() if file_input else []
        source_content = self.query_one("#req_input", Input).value.strip()
        provider = self.query_one("#provider_id", Input).value.strip() or self.cfg.agent_cli_id
        model = self.query_one("#model_id", Input).value.strip() or provider_default_model(provider, self.cfg)
        project_dir_raw = self.query_one("#project_dir", Input).value.strip()
        project_dir = Path(project_dir_raw) if project_dir_raw else default_project_dir()
        return prompt_files, source_content, provider, model, project_dir

    @work(thread=True, exclusive=True)
    def run_flow_worker(self, include_configure: bool) -> None:
        prompt_files, source_content, provider, model, project_dir = self._resolve_inputs()
        try:
            if not prompt_files and not source_content:
                self.call_from_thread(self._set_status, "Provide prompt files or requirements text")
                return

            from prompter import collect_source_documents

            self.call_from_thread(self._set_phase, PromptFlowPhase.ANALYZE, "running", "Analyzing requirements")
            content = source_content or collect_source_documents(prompt_files)
            analysis_result = asyncio.run(
                run_analysis_session(
                    content=content,
                    model=model,
                    provider_id=provider,
                    status_callback=self._status_cb,
                    stream_callback=self._stream_cb,
                )
            )
            self.call_from_thread(self._set_phase, PromptFlowPhase.ANALYZE, "done", "Analysis complete")

            questions = analysis_result.get("questions", [])
            self.call_from_thread(self._set_phase, PromptFlowPhase.QA, "running", f"Questions found: {len(questions)}")
            qa_pairs = []
            for q in questions:
                question = q.get("question", "")
                why = q.get("why", "")
                self.call_from_thread(self._append_log, f"[qa] {question} ({why})")
                qa_pairs.append({"question": question, "answer": ""})
            self.call_from_thread(self._set_phase, PromptFlowPhase.QA, "done", "Q&A step complete (blank answers by default)")

            self.call_from_thread(self._set_phase, PromptFlowPhase.GENERATE, "running", "Generating prompts")
            generated = asyncio.run(
                run_generation_session(
                    content=content,
                    qa_pairs=qa_pairs,
                    model=model,
                    provider_id=provider,
                    status_callback=self._status_cb,
                    stream_callback=self._stream_cb,
                )
            )
            self.call_from_thread(self._set_phase, PromptFlowPhase.GENERATE, "done", "Prompt generation complete")

            self.call_from_thread(self._set_phase, PromptFlowPhase.WRITE, "running", "Writing prompt files")
            write_prompt_files(
                generated,
                Path("prompts"),
                overwrite=self.args.prompt_overwrite,
                status_callback=self._status_cb,
            )
            self.call_from_thread(self._set_phase, PromptFlowPhase.WRITE, "done", "Prompt files written")

            if include_configure:
                self.call_from_thread(self._set_phase, PromptFlowPhase.CONFIGURE, "running", "Detecting stack")
                asyncio.run(
                    run_configure(
                        configure_model=model,
                        provider_id=provider,
                        status_callback=self._status_cb,
                        stream_callback=self._stream_cb,
                    )
                )
                self.call_from_thread(self._set_phase, PromptFlowPhase.CONFIGURE, "done", "Configuration complete")

            cmd = build_handoff_command(project_dir=project_dir, provider_id=provider, model=model)
            self.handoff_command = cmd
            self.call_from_thread(self._set_phase, PromptFlowPhase.HANDOFF, "done", "Press H to hand off to native coding agent TUI")
            self.call_from_thread(self._append_log, "[handoff] " + " ".join(cmd))
        except Exception as exc:
            self.call_from_thread(self._set_status, f"Error: {exc}")
            self.call_from_thread(self._append_log, f"[error] {exc}")

    @work(thread=True, exclusive=True)
    def run_configure_worker(self) -> None:
        _, _, provider, model, project_dir = self._resolve_inputs()
        try:
            self.call_from_thread(self._set_phase, PromptFlowPhase.CONFIGURE, "running", "Detecting stack")
            asyncio.run(
                run_configure(
                    configure_model=model,
                    provider_id=provider,
                    status_callback=self._status_cb,
                    stream_callback=self._stream_cb,
                )
            )
            self.call_from_thread(self._set_phase, PromptFlowPhase.CONFIGURE, "done", "Configuration complete")
            cmd = build_handoff_command(project_dir=project_dir, provider_id=provider, model=model)
            self.handoff_command = cmd
            self.call_from_thread(self._set_phase, PromptFlowPhase.HANDOFF, "done", "Press H to hand off to native coding agent TUI")
            self.call_from_thread(self._append_log, "[handoff] " + " ".join(cmd))
        except Exception as exc:
            self.call_from_thread(self._set_status, f"Error: {exc}")
            self.call_from_thread(self._append_log, f"[error] {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACAP Textual prep TUI")
    parser.add_argument("--project-dir", type=Path, default=default_project_dir())
    parser.add_argument("--agent-cli", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--prompt-files", nargs="+", default=None)
    parser.add_argument("--prompt-overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = AcapTuiApp(args)
    handoff_command = app.run()
    if handoff_command:
        subprocess.run(handoff_command, check=False)


if __name__ == "__main__":
    main()
