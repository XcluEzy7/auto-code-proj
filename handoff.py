"""Handoff command execution with logging support."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from config import get_config
from run_logging import RunLogger
from stream_cleaning import StreamCleaner


def run_handoff_command_with_logging(
    handoff_command: list[str],
    run_logger: RunLogger | None,
    provider: str = "claude",
    stream_mode: str = "assistant_text",
    show_thinking: bool = False,
) -> int:
    """Stream handoff command output to terminal and structured JSONL log."""
    cleaner = StreamCleaner(
        mode=stream_mode,  # type: ignore[arg-type]
        show_thinking=show_thinking,
    )
    if run_logger is not None:
        run_logger.log_event(
            phase="agent",
            event_type="lifecycle",
            message="handoff_started",
            meta={"command": " ".join(handoff_command)},
        )

    proc = subprocess.Popen(
        handoff_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    q: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def _reader(stream_name: str, handle: object | None) -> None:
        if handle is None:
            q.put((stream_name, None))
            return
        for line in handle:
            q.put((stream_name, line))
        q.put((stream_name, None))

    threads = [
        threading.Thread(target=_reader, args=("stdout", proc.stdout), daemon=True),
        threading.Thread(target=_reader, args=("stderr", proc.stderr), daemon=True),
    ]
    for t in threads:
        t.start()

    completed_streams = 0
    while completed_streams < 2:
        stream_name, line = q.get()
        if line is None:
            completed_streams += 1
            continue
        text = line.rstrip("\n")
        rendered_lines = cleaner.ingest(
            provider=provider,
            stream=stream_name,
            raw_line=text,
        )
        for rendered in rendered_lines:
            if stream_name == "stdout":
                print(rendered, flush=True)
            else:
                print(rendered, file=sys.stderr, flush=True)
        if run_logger is not None:
            run_logger.log_event(
                phase="agent",
                event_type="stream",
                message=text,
                stream=stream_name,
            )

    return_code = proc.wait()
    if run_logger is not None:
        run_logger.log_event(
            phase="agent",
            event_type="lifecycle",
            message="handoff_finished",
            meta={"return_code": str(return_code)},
        )
    return return_code
