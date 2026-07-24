"""JARVIS Mk II visual system.

The package is deliberately independent from the legacy ``ui.py`` module so
the visual language can evolve without changing JARVIS' public UI contract.
"""

from .core import CoreRenderer
from .pet import PetOverlayWindow
from .state import VisualState, VisualStateController, normalize_state

__all__ = [
    "CoreRenderer",
    "PetOverlayWindow",
    "VisualState",
    "VisualStateController",
    "normalize_state",
]
