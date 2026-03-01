"""Service-layer helpers for ACAP TUI."""

from __future__ import annotations

from pathlib import Path

from config import get_config
from tui_core import PromptFlowPhase

PHASE_WEIGHTS: dict[PromptFlowPhase, int] = {
    PromptFlowPhase.ANALYZE: 15,
    PromptFlowPhase.QA: 15,
    PromptFlowPhase.GENERATE: 35,
    PromptFlowPhase.WRITE: 10,
    PromptFlowPhase.CONFIGURE: 20,
    PromptFlowPhase.HANDOFF: 5,
}

PHASE_ORDER: list[PromptFlowPhase] = [
    PromptFlowPhase.ANALYZE,
    PromptFlowPhase.QA,
    PromptFlowPhase.GENERATE,
    PromptFlowPhase.WRITE,
    PromptFlowPhase.CONFIGURE,
    PromptFlowPhase.HANDOFF,
]


def compute_flow_completion(current_phase: PromptFlowPhase) -> int:
    """Return integer completion percentage using weighted phase totals."""
    total = 0
    for phase in PHASE_ORDER:
        total += PHASE_WEIGHTS[phase]
        if phase == current_phase:
            break
    return min(total, 100)


def build_handoff_command(
    project_dir: Path,
    provider_id: str,
    model: str,
) -> list[str]:
    """Build command that starts native coding-agent CLI flow after prep."""
    return [
        "uv",
        "run",
        "python3",
        "acaps.py",
        "--project-dir",
        str(project_dir),
        "--agent-cli",
        provider_id,
        "--model",
        model,
    ]


def default_project_dir() -> Path:
    """Return default project directory from config conventions."""
    cfg = get_config()
    return Path(cfg.project_dir_prefix) / "autonomous_demo_project"


__all__ = [
    "PromptFlowPhase",
    "PHASE_WEIGHTS",
    "PHASE_ORDER",
    "compute_flow_completion",
    "build_handoff_command",
    "default_project_dir",
]
