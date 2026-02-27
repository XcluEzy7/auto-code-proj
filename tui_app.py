#!/usr/bin/env python3
"""Textual TUI for ACAP prompt generation + configure + handoff."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, RichLog, Static

from config import get_config
from configure import run_configure
from prompter import collect_source_documents, run_analysis_session, run_generation_session, write_prompt_files
from provider_cli import provider_default_model
from tui_models import ClarifyingQuestion, PromptFlowPhase
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
    .hidden {
      display: none;
    }
    #req_input {
      height: 6;
      margin-bottom: 1;
    }
    #qa_box {
      border: round #ccc;
      padding: 1;
      margin-bottom: 1;
      height: 10;
    }
    #qa_answer {
      margin-top: 1;
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
        Binding("enter", "menu_select", "Select/Save", priority=True),
        Binding("e", "toggle_edit_mode", "Edit Fields", priority=True),
        Binding("n", "qa_next", "Next Q", priority=True),
        Binding("p", "qa_prev", "Prev Q", priority=True),
        Binding("s", "qa_submit", "Submit Q&A", priority=True),
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
        self.handoff_command: list[str] | None = None
        self.edit_mode: bool = False

        self.pending_content: str | None = None
        self.pending_provider: str | None = None
        self.pending_model: str | None = None
        self.pending_project_dir: Path | None = None
        self.pending_include_configure: bool = False

        self.qa_mode: bool = False
        self.questions: list[ClarifyingQuestion] = []
        self.qa_index: int = 0

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
                yield Input(value=default_model, placeholder="Model", id="model_id")
                yield Input(
                    placeholder="Paste requirements text here (disabled when prompt files are set)",
                    id="req_input",
                )
                with Vertical(id="qa_box"):
                    yield Static("", id="qa_title")
                    yield Static("", id="qa_why")
                    yield Input(placeholder="Type answer and press Enter to save", id="qa_answer")
                log = RichLog(id="logs")
                log.add_class("hidden")
                yield log
        yield Footer()

    def on_mount(self) -> None:
        self._render_menu()
        self._render_timeline()
        self._set_inputs_enabled(False)
        self.query_one("#qa_box", Vertical).add_class("hidden")
        self._refresh_source_mode()
        self.set_interval(0.7, self._pulse_arcade)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "prompt_files":
            self._refresh_source_mode()

    def _refresh_source_mode(self) -> None:
        prompt_files = self.query_one("#prompt_files", Input).value.strip()
        req_input = self.query_one("#req_input", Input)
        if prompt_files:
            req_input.value = ""
            req_input.add_class("hidden")
            req_input.disabled = True
            self._set_status("Using PRD files as source-of-truth. Questionnaire will refine details.")
        else:
            req_input.remove_class("hidden")
            req_input.disabled = not self.edit_mode

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for widget_id in ("#prompt_files", "#project_dir", "#provider_id", "#model_id"):
            input_widget = self.query_one(widget_id, Input)
            input_widget.disabled = not enabled

        req_input = self.query_one("#req_input", Input)
        if self.query_one("#prompt_files", Input).value.strip():
            req_input.disabled = True
        else:
            req_input.disabled = not enabled

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
            lines.append(f"{phase.value.upper():<10} {self.phase_state[phase]}")
        self.query_one("#timeline", Static).update("\n".join(lines))

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _append_log(self, line: str) -> None:
        self.query_one("#logs", RichLog).write(line)

    def _set_phase(self, phase: PromptFlowPhase, state: str, message: str = "") -> None:
        self.phase_state[phase] = state
        self._render_timeline()
        self.query_one("#arcade", ArcadeProgress).set_progress(compute_flow_completion(phase))
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

    def _resolve_inputs(self) -> tuple[list[str], str, str, str, Path]:
        file_input = self.query_one("#prompt_files", Input).value.strip()
        prompt_files = file_input.split() if file_input else []
        source_content = self.query_one("#req_input", Input).value.strip()
        provider = self.query_one("#provider_id", Input).value.strip() or self.cfg.agent_cli_id
        model = self.query_one("#model_id", Input).value.strip() or provider_default_model(provider, self.cfg)
        project_dir_raw = self.query_one("#project_dir", Input).value.strip()
        project_dir = Path(project_dir_raw) if project_dir_raw else default_project_dir()
        return prompt_files, source_content, provider, model, project_dir

    def _show_questionnaire(self, questions: list[ClarifyingQuestion]) -> None:
        self.questions = questions
        self.qa_index = 0
        self.qa_mode = True
        self.query_one("#qa_box", Vertical).remove_class("hidden")
        self.query_one("#qa_answer", Input).disabled = False
        self._update_questionnaire_view()
        self.set_focus(self.query_one("#qa_answer", Input))
        self._set_status("Answer clarifying questions. Enter saves, N/P navigate, S submits.")

    def _hide_questionnaire(self) -> None:
        self.qa_mode = False
        self.query_one("#qa_box", Vertical).add_class("hidden")
        self.query_one("#qa_answer", Input).disabled = True

    def _update_questionnaire_view(self) -> None:
        if not self.questions:
            self._hide_questionnaire()
            return
        current = self.questions[self.qa_index]
        self.query_one("#qa_title", Static).update(
            f"Q{self.qa_index + 1}/{len(self.questions)}: {current.question}"
        )
        self.query_one("#qa_why", Static).update(f"Why: {current.why}" if current.why else "")
        self.query_one("#qa_answer", Input).value = current.answer

    def _save_current_answer(self) -> None:
        if not self.qa_mode or not self.questions:
            return
        answer = self.query_one("#qa_answer", Input).value.strip()
        self.questions[self.qa_index].answer = answer

    def action_menu_up(self) -> None:
        if self.qa_mode:
            return
        self.selected_index = (self.selected_index - 1) % len(self.MENU_ITEMS)
        self._render_menu()

    def action_menu_down(self) -> None:
        if self.qa_mode:
            return
        self.selected_index = (self.selected_index + 1) % len(self.MENU_ITEMS)
        self._render_menu()

    def action_menu_select(self) -> None:
        if self.qa_mode:
            self._save_current_answer()
            self.action_qa_next()
            return

        if self.edit_mode:
            self._set_status("Exit edit mode with E before selecting a menu action")
            return

        choice = self.MENU_ITEMS[self.selected_index]
        if choice == "Quit":
            self.exit(None)
            return
        if choice == "Start End-to-End Prep":
            self.run_flow_worker(include_configure=True)
            return
        if choice == "Prompt Wizard Only":
            self.run_flow_worker(include_configure=False)
            return
        if choice == "Configure Only":
            self.run_configure_worker()

    def action_toggle_edit_mode(self) -> None:
        if self.qa_mode:
            self._set_status("Questionnaire is active. Finish Q&A before editing source fields.")
            return
        self.edit_mode = not self.edit_mode
        self._set_inputs_enabled(self.edit_mode)
        if self.edit_mode:
            self._set_status("Edit mode enabled: type in fields. Press E to return to menu mode.")
        else:
            self._set_status("Menu mode enabled: use arrows + Enter to select workflow.")

    def action_qa_next(self) -> None:
        if not self.qa_mode or not self.questions:
            return
        self._save_current_answer()
        self.qa_index = min(self.qa_index + 1, len(self.questions) - 1)
        self._update_questionnaire_view()

    def action_qa_prev(self) -> None:
        if not self.qa_mode or not self.questions:
            return
        self._save_current_answer()
        self.qa_index = max(self.qa_index - 1, 0)
        self._update_questionnaire_view()

    def action_qa_submit(self) -> None:
        if not self.qa_mode:
            self._set_status("No active questionnaire to submit")
            return
        self._save_current_answer()
        self._hide_questionnaire()
        self._set_phase(PromptFlowPhase.QA, "done", "Q&A completed. Generating prompts...")
        self.run_generation_worker()

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

    @work(thread=True, exclusive=True)
    def run_flow_worker(self, include_configure: bool) -> None:
        prompt_files, source_content, provider, model, project_dir = self._resolve_inputs()
        try:
            if not prompt_files and not source_content:
                self.call_from_thread(self._set_status, "Provide prompt files or requirements text")
                return

            if prompt_files:
                content = collect_source_documents(prompt_files)
            else:
                content = source_content

            self.pending_content = content
            self.pending_provider = provider
            self.pending_model = model
            self.pending_project_dir = project_dir
            self.pending_include_configure = include_configure

            self.call_from_thread(self._set_phase, PromptFlowPhase.ANALYZE, "running", "Analyzing requirements")
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

            questions = [
                ClarifyingQuestion(
                    question=q.get("question", ""),
                    why=q.get("why", ""),
                )
                for q in analysis_result.get("questions", [])
                if q.get("question")
            ]

            if questions:
                self.call_from_thread(self._set_phase, PromptFlowPhase.QA, "running", f"Questions found: {len(questions)}")
                self.call_from_thread(self._show_questionnaire, questions)
            else:
                self.call_from_thread(self._set_phase, PromptFlowPhase.QA, "done", "No clarifying questions")
                self.run_generation_worker()
        except Exception as exc:
            self.call_from_thread(self._set_status, f"Error: {exc}")
            self.call_from_thread(self._append_log, f"[error] {exc}")

    @work(thread=True, exclusive=True)
    def run_generation_worker(self) -> None:
        try:
            if not self.pending_content or not self.pending_provider or not self.pending_model:
                self.call_from_thread(self._set_status, "Missing flow context for generation")
                return

            qa_pairs = [
                {"question": q.question, "answer": q.answer}
                for q in self.questions
                if q.answer
            ]

            self.call_from_thread(self._set_phase, PromptFlowPhase.GENERATE, "running", "Generating prompts")
            generated = asyncio.run(
                run_generation_session(
                    content=self.pending_content,
                    qa_pairs=qa_pairs,
                    model=self.pending_model,
                    provider_id=self.pending_provider,
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

            if self.pending_include_configure:
                self.call_from_thread(self._set_phase, PromptFlowPhase.CONFIGURE, "running", "Detecting stack")
                asyncio.run(
                    run_configure(
                        configure_model=self.pending_model,
                        provider_id=self.pending_provider,
                        status_callback=self._status_cb,
                        stream_callback=self._stream_cb,
                    )
                )
                self.call_from_thread(self._set_phase, PromptFlowPhase.CONFIGURE, "done", "Configuration complete")

            project_dir = self.pending_project_dir or default_project_dir()
            cmd = build_handoff_command(
                project_dir=project_dir,
                provider_id=self.pending_provider,
                model=self.pending_model,
            )
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
