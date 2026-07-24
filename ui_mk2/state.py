"""State normalization and smooth visual transitions for JARVIS Mk II."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VisualState(str, Enum):
    DORMANT = "DORMANT"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    EXECUTING = "EXECUTING"
    ERROR = "ERROR"


_ALIASES = {
    "INITIALISING": VisualState.DORMANT,
    "INITIALIZING": VisualState.DORMANT,
    "STANDBY": VisualState.DORMANT,
    "SLEEPING": VisualState.DORMANT,
    "IDLE": VisualState.DORMANT,
    "READY": VisualState.LISTENING,
    "PROCESSING": VisualState.EXECUTING,
    "WORKING": VisualState.EXECUTING,
    "FAILURE": VisualState.ERROR,
    "FAILED": VisualState.ERROR,
}


def normalize_state(value: str | VisualState) -> VisualState:
    if isinstance(value, VisualState):
        return value
    candidate = str(value or "").strip().upper()
    if candidate in _ALIASES:
        return _ALIASES[candidate]
    try:
        return VisualState(candidate)
    except ValueError:
        return VisualState.DORMANT


@dataclass(frozen=True)
class StateSpec:
    primary: str
    secondary: str
    intensity: float
    ring_speed: float
    lens_offset_x: float
    lens_offset_y: float
    waveform: float


STATE_SPECS = {
    VisualState.DORMANT: StateSpec(
        "#27C8FF", "#247EAE", 0.58, 0.0, 0.0, 0.0, 0.0
    ),
    VisualState.LISTENING: StateSpec(
        "#27C8FF", "#6DE2FF", 1.0, 0.055, 0.0, 0.0, 0.22
    ),
    VisualState.THINKING: StateSpec(
        "#168AB9", "#285369", 0.82, 0.22, 0.16, -0.16, 0.08
    ),
    VisualState.SPEAKING: StateSpec(
        "#27C8FF", "#6DE2FF", 1.0, 0.11, 0.0, 0.0, 1.0
    ),
    VisualState.EXECUTING: StateSpec(
        "#168AB9", "#285369", 0.72, -0.18, -0.15, 0.17, 0.12
    ),
    VisualState.ERROR: StateSpec(
        "#FF405C", "#FF9AA9", 0.92, 0.0, 0.0, 0.0, 0.0
    ),
}


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


class VisualStateController:
    """Keeps product state discrete while visual values interpolate smoothly."""

    def __init__(self, state: str | VisualState = VisualState.DORMANT):
        self.state = normalize_state(state)
        self.previous = self.state
        self.progress = 1.0
        self.duration = 0.52
        self.reduced_motion = False

    @property
    def spec(self) -> StateSpec:
        return STATE_SPECS[self.state]

    @property
    def previous_spec(self) -> StateSpec:
        return STATE_SPECS[self.previous]

    def set_state(self, state: str | VisualState) -> bool:
        next_state = normalize_state(state)
        if next_state == self.state:
            return False
        self.previous = self.state
        self.state = next_state
        self.progress = 1.0 if self.reduced_motion else 0.0
        return True

    def advance(self, dt: float) -> None:
        if self.progress < 1.0:
            self.progress = min(1.0, self.progress + max(0.0, dt) / self.duration)

    def mix(self, previous: float, target: float) -> float:
        amount = _smoothstep(self.progress)
        return previous + (target - previous) * amount

    def value(self, name: str) -> float:
        return self.mix(
            float(getattr(self.previous_spec, name)),
            float(getattr(self.spec, name)),
        )
