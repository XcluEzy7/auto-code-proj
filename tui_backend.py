#!/usr/bin/env python3
"""Python TUI Backend - JSONL protocol server for OpenTui frontend."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from config import get_config, reload_config
from configure import run_configure
from handoff import run_handoff_command_with_logging
from prompter import (
    collect_source_documents,
    run_analysis_session,
    run_generation_session,
    write_prompt_files,
)
from provider_cli import provider_default_model
from run_logging import RunLogger
from tui_services import build_handoff_command, default_project_dir


# ============================================================================
# Types
# ============================================================================

type Phase = str  # "analyze" | "qa" | "generate" | "write" | "configure" | "handoff"
type PhaseState = str  # "queued" | "running" | "done" | "warn" | "error"


@dataclass
class PhaseInfo:
    state: PhaseState
    message: str
    progress: int


@dataclass
class Question:
    question: str
    why: str
    answer: str = ""


@dataclass
class FlowState:
    phases: dict[Phase, PhaseInfo] = field(default_factory=lambda: {
        "analyze": PhaseInfo("queued", "Waiting", 0),
        "qa": PhaseInfo("queued", "Waiting", 0),
        "generate": PhaseInfo("queued", "Waiting", 0),
        "write": PhaseInfo("queued", "Waiting", 0),
        "configure": PhaseInfo("queued", "Waiting", 0),
        "handoff": PhaseInfo("queued", "Waiting", 0),
    })
    questions: list[Question] = field(default_factory=list)
    current_question_index: int = 0
    handoff_command: list[str] | None = None


# ============================================================================
# JSONL Protocol
# ============================================================================

class ProtocolHandler:
    def __init__(self):
        self.flow = FlowState()
        self.run_logger: RunLogger | None = None
        self.cfg = get_config()
        self.pending_content: str | None = None
        self.pending_provider: str | None = None
        self.pending_model: str | None = None
        self.pending_project_dir: Path | None = None

    def send(self, msg_id: str, msg_type: str, **kwargs) -> None:
        response = {"id": msg_id, "type": msg_type, **kwargs}
        print(json.dumps(response), flush=True)

    async def handle(self, line: str) -> None:
        try:
            request = json.loads(line)
            req_id = request.get("id", str(uuid.uuid4()))
            req_type = request.get("type")
            payload = request.get("payload", {})

            handler = getattr(self, f"handle_{req_type}", None)
            if handler:
                await handler(req_id, payload)
            else:
                self.send(req_id, "error", message=f"Unknown request type: {req_type}")
        except json.JSONDecodeError as e:
            self.send("error", "error", message=f"Invalid JSON: {e}")
        except Exception as e:
            self.send("error", "error", message=f"Handler error: {e}")

    async def handle_collect(self, req_id: str, payload: dict) -> None:
        """Handle collect request - gather source documents."""
        self.send(req_id, "ack")
        prompt_files = payload.get("prompt_files", [])
        source_content = payload.get("source_content", "")

        try:
            if prompt_files:
                content = collect_source_documents(prompt_files)
            else:
                content = source_content
            self.pending_content = content
            self.send(req_id, "done", content_preview=content[:200] + "..." if len(content) > 200 else content)
        except Exception as e:
            self.send(req_id, "error", message=str(e))

    async def handle_analyze(self, req_id: str, payload: dict) -> None:
        """Handle analyze request - AI analysis session."""
        self._set_phase("analyze", "running", "Analyzing requirements...")
        self.send(req_id, "ack")

        content = payload.get("content") or self.pending_content
        provider = payload.get("provider_id", self.cfg.agent_cli_id)
        model = payload.get("model") or provider_default_model(provider, self.cfg)

        self.pending_provider = provider
        self.pending_model = model

        try:
            def status_cb(phase: str, msg: str) -> None:
                self._set_phase("analyze", "running", msg)

            def stream_cb(stream: str, text: str) -> None:
                self.send(req_id, "stream", stream=stream, text=text)

            result = await run_analysis_session(
                content=content,
                model=model,
                provider_id=provider,
                status_callback=status_cb,
                stream_callback=stream_cb,
            )

            questions = result.get("questions", [])
            self.flow.questions = [
                Question(q=q.get("question", ""), why=q.get("why", ""))
                for q in questions
            ]

            self._set_phase("analyze", "done", f"Analysis complete: {len(questions)} questions")
            self.send(req_id, "done", analysis=result.get("analysis"), question_count=len(questions))
        except Exception as e:
            self._set_phase("analyze", "error", str(e))
            self.send(req_id, "error", message=str(e))

    async def handle_qa(self, req_id: str, payload: dict) -> None:
        """Handle Q&A - submit answers to clarifying questions."""
        self.send(req_id, "ack")
        answers = payload.get("answers", [])

        for i, answer in enumerate(answers):
            if i < len(self.flow.questions):
                self.flow.questions[i].answer = answer

        self._set_phase("qa", "done", f"Q&A completed: {len(answers)} answers")
        self.send(req_id, "done", answers=answers)

    async def handle_generate(self, req_id: str, payload: dict) -> None:
        """Handle generate request - AI generation session."""
        self._set_phase("generate", "running", "Generating prompts...")
        self.send(req_id, "ack")

        try:
            qa_pairs = [
                {"question": q.question, "answer": q.answer}
                for q in self.flow.questions
                if q.answer
            ]

            def status_cb(phase: str, msg: str) -> None:
                self._set_phase("generate", "running", msg)

            def stream_cb(stream: str, text: str) -> None:
                self.send(req_id, "stream", stream=stream, text=text)

            generated = await run_generation_session(
                content=self.pending_content or "",
                qa_pairs=qa_pairs,
                model=self.pending_model or self.cfg.claude_model,
                provider_id=self.pending_provider or self.cfg.agent_cli_id,
                status_callback=status_cb,
                stream_callback=stream_cb,
            )

            self._set_phase("generate", "done", "Prompt generation complete")
            self.send(req_id, "done", generated=generated)
        except Exception as e:
            self._set_phase("generate", "error", str(e))
            self.send(req_id, "error", message=str(e))

    async def handle_write(self, req_id: str, payload: dict) -> None:
        """Handle write request - write prompt files to disk."""
        self._set_phase("write", "running", "Writing files...")
        self.send(req_id, "ack")

        generated = payload.get("
generated
overwrite

        write_prompt_files(
            generated,
            prompts_dir,
            overwrite=overwrite,
            status_callback=lambda p, m: self._set_phase("write", "running", m),
        )

        self._set_phase("write", "done", "Files written successfully")
        self.send(req_id, "done")

    async def handle_configure(self, req_id: str, payload: dict) -> None:
        """Handle configure request - detect tech stack."""
        self._set_phase("configure", "running", "Detecting tech stack...")
        self.send(req_id, "ack")

        provider = payload.get("provider_id", self.pending_provider or self.cfg.agent_cli_id)
        model = payload.get("model", self.pending_model) or provider_default_model(provider, self.cfg)
        project_dir = Path(payload.get("project_dir", str(default_project_dir())))
        self.pending_project_dir = project_dir

        try:
            def status_cb(phase: str, msg: str) -> None:
                self._set_phase("configure", "running", msg)

            def stream_cb(stream: str, text: str) -> None:
                self.send(req_id, "stream", stream=stream, text=text)

            await run_configure(
                configure_model=model,
                provider_id=provider,
                status_callback=status_cb,
                stream_callback=stream_cb,
            )

            self._set_phase("configure", "done", "Configuration complete")
            self.send(req_id, "done")
        except Exception as e:
            self._set_phase("configure", "error", str(e))
            self.send(req_id, "error", message=str(e))

    async def handle_handoff(self, req_id: str, payload: dict) -> None:
        """Handle handoff request - execute handoff command."""
        self._set_phase("handoff", "running", "Executing handoff...")
        self.send(req_id, "ack")

        provider = payload.get("provider_id", self.pending_provider or self.cfg.agent_cli_id)
        model = payload.get("model", self.pending_model or self.cfg.claude_model)
        project_dir = self.pending_project_dir or default_project_dir()

        cmd = build_handoff_command(
            project_dir=project_dir,
            provider_id=provider,
            model=model,
        )
        self.flow.handoff_command = cmd

        try:
            return_code = run_handoff_command_with_logging(
                cmd,
                self.run_logger,
                provider=provider,
                stream_mode=self.cfg.agent_stream_stdout_mode,
                show_thinking=self.cfg.agent_stream_show_thinking,
            )

            if return_code == 0:
                self._set_phase("handoff", "done", "Handoff complete")
            else:
                self._set_phase("handoff", "error", f"Exit code: {return_code}")

            self.send(req_id, "done", return_code=return_code, command=cmd)
        except Exception as e:
            self._set_phase("handoff", "error", str(e))
            self.send(req_id, "error", message=str(e))

    async def handle_status(self, req_id: str, payload: dict) -> None:
        """Handle status request - return current state."""
        self.send(
            req_id,
            "data",
            phases={k: {"state": v.state, "message": v.message, "progress": v.progress}
                  for k, v in self.flow.phases.items()},
            questions=[
                {"question": q.question, "why": q.why, "answer": q.answer}
                for q in self.flow.questions
            ],
            current_question_index=self.flow.current_question_index,
            handoff_command=self.flow.handoff_command,
        )

    def _set_phase(self, phase: str, state: PhaseState, message: str) -> None:
        """Update phase state and notify."""
        if phase in self.flow.phases:
            progress = self._compute_progress(phase, state)
            self.flow.phases[phase] = PhaseInfo(state, message, progress)

    def _compute_progress(self, phase: str, state: PhaseState) -> int:
        """Compute completion percentage based on phase weights."""
        weights = {
            "analyze": 15,
            "qa": 15,
            "generate": 35,
            "write": 10,
            "configure": 20,
            "handoff": 5,
        }
        progress = 0
        for k, w in weights.items():
            if k == phase:
                if state == "done":
                    progress += w
                break
            progress += w
        return min(progress, 100)


# ============================================================================
# Main Entry Point
# ============================================================================

async def main() -> None:
    """Main entry point for TUI backend."""
    handler = ProtocolHandler()

    # Signal ready
    print(json.dumps({"type": "ready"}), flush=True)

    # Read and process commands from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        await handler.handle(line)


if __name__ == "__main__":
    asyncio.run(main())