#!/usr/bin/env python3
"""Utility to locate and preview the latest ACAP run log."""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from config import get_config


def find_latest_run_log(log_dir: Path) -> Path | None:
    """Return the newest JSONL log file in log_dir, or None when absent."""
    if not log_dir.exists() or not log_dir.is_dir():
        return None
    candidates = [path for path in log_dir.iterdir() if path.is_file() and path.suffix == ".jsonl"]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_last_lines(path: Path, line_count: int) -> list[str]:
    """Read the last N lines from a text file."""
    if line_count <= 0:
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in deque(handle, maxlen=line_count)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print the latest TUI run log path or preview contents.")
    parser.add_argument(
        "--tail",
        type=int,
        default=0,
        help="Print the last N lines of the latest log file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = get_config()
    log_dir = Path(cfg.agent_run_log_dir)
    latest = find_latest_run_log(log_dir)
    if latest is None:
        print(f"No run logs found in {log_dir}")
        return 1

    print(str(latest))
    if args.tail > 0:
        print()
        for line in read_last_lines(latest, args.tail):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

