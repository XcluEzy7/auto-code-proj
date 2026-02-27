"""Shared models for the ACAP Textual TUI."""

from dataclasses import dataclass, field
from enum import Enum


class PromptFlowPhase(str, Enum):
    """Ordered phases in the prep flow."""

    ANALYZE = "analyze"
    QA = "qa"
    GENERATE = "generate"
    WRITE = "write"
    CONFIGURE = "configure"
    HANDOFF = "handoff"


@dataclass
class PhaseState:
    """Runtime state for a phase."""

    phase: PromptFlowPhase
    label: str
    status: str = "queued"
    message: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class FlowState:
    """Top-level UI state for prompt/configure flow."""

    current_phase: PromptFlowPhase = PromptFlowPhase.ANALYZE
    stream_mode: bool = False
    logs: list[str] = field(default_factory=list)
