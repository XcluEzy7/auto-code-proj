#!/usr/bin/env python3
"""Provider-aware stream cleaning for human-readable stdout rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

StreamRenderMode = Literal["assistant_text", "compact", "raw"]


@dataclass
class StreamCleaner:
    """Render raw stream lines into cleaner human-facing output."""

    mode: StreamRenderMode = "assistant_text"
    show_thinking: bool = False

    def ingest(self, provider: str, stream: str, raw_line: str) -> list[str]:
        if self.mode == "raw":
            return [raw_line]
        if stream != "stdout":
            return [raw_line]
        if provider.strip().lower() != "omp":
            return [raw_line]
        return _clean_omp_json_line(
            raw_line=raw_line,
            mode=self.mode,
            show_thinking=self.show_thinking,
        )


def _clean_omp_json_line(
    *,
    raw_line: str,
    mode: StreamRenderMode,
    show_thinking: bool,
) -> list[str]:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        return [raw_line]

    event_type = payload.get("type")
    if not isinstance(event_type, str):
        return [raw_line]

    if event_type == "message_update":
        update = payload.get("assistantMessageEvent")
        if not isinstance(update, dict):
            return []
        update_type = update.get("type")
        if not isinstance(update_type, str):
            return []

        if update_type == "text_delta":
            delta = update.get("delta")
            if isinstance(delta, str) and delta:
                return [delta]
            return []

        if update_type == "thinking_delta":
            if not show_thinking:
                return []
            delta = update.get("delta")
            if isinstance(delta, str) and delta:
                return [f"[thinking] {delta}"]
            return []

        if mode == "compact" and update_type in {"text_start", "text_end"}:
            return [f"[{update_type}]"]
        return []

    if mode == "compact" and event_type in {"message_end", "turn_start", "turn_end"}:
        return [f"[{event_type}]"]

    return []
