"""Structured per-run logging for TUI prep + handoff agent output."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sanitize_label(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", lowered).strip("-")
    return cleaned or "unknown"


@dataclass
class RunLogger:
    """Append-only JSONL logger for one TUI run."""

    enabled: bool
    run_id: str
    provider: str
    model: str
    project_dir: str
    log_file: Path | None = None
    _write_failed: bool = False

    @classmethod
    def create(
        cls,
        *,
        enabled: bool,
        base_dir: Path,
        provider: str,
        model: str,
        project_dir: Path,
    ) -> "RunLogger":
        run_id = uuid.uuid4().hex[:8]
        if not enabled:
            return cls(
                enabled=False,
                run_id=run_id,
                provider=provider,
                model=model,
                project_dir=str(project_dir),
                log_file=None,
            )

        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            filename = (
                f"{_utc_stamp()}_{_sanitize_label(provider)}_"
                f"{_sanitize_label(model)}_{run_id}.jsonl"
            )
            log_file = base_dir / filename
            return cls(
                enabled=True,
                run_id=run_id,
                provider=provider,
                model=model,
                project_dir=str(project_dir),
                log_file=log_file,
            )
        except OSError:
            return cls(
                enabled=False,
                run_id=run_id,
                provider=provider,
                model=model,
                project_dir=str(project_dir),
                log_file=None,
            )

    def log_event(
        self,
        *,
        phase: str,
        event_type: str,
        message: str,
        stream: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or self.log_file is None or self._write_failed:
            return

        payload: dict[str, Any] = {
            "ts": _utc_iso(),
            "run_id": self.run_id,
            "phase": phase,
            "event_type": event_type,
            "stream": stream,
            "provider": self.provider,
            "model": self.model,
            "project_dir": self.project_dir,
            "message": message,
        }
        if meta:
            payload["meta"] = meta

        try:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except OSError:
            self._write_failed = True

