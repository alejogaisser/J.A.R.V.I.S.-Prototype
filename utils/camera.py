from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CameraProfile:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    jpeg_quality: int = 90


def profile_from_config(config: Mapping | None = None) -> CameraProfile:
    config = config or {}
    return CameraProfile(
        width=max(640, min(3840, int(config.get("camera_width", 1920)))),
        height=max(480, min(2160, int(config.get("camera_height", 1080)))),
        fps=max(15, min(60, int(config.get("camera_fps", 30)))),
        jpeg_quality=max(80, min(95, int(config.get("camera_jpeg_quality", 90)))),
    )


def configure_capture(cap, cv2, profile: CameraProfile) -> dict[str, float]:
    """Request a low-latency native webcam format; unsupported properties are harmless."""
    properties = (
        ("CAP_PROP_FOURCC", float(cv2.VideoWriter_fourcc(*"MJPG"))),
        ("CAP_PROP_FRAME_WIDTH", float(profile.width)),
        ("CAP_PROP_FRAME_HEIGHT", float(profile.height)),
        ("CAP_PROP_FPS", float(profile.fps)),
        ("CAP_PROP_BUFFERSIZE", 1.0),
        ("CAP_PROP_AUTOFOCUS", 1.0),
        ("CAP_PROP_AUTO_EXPOSURE", 0.75),
    )
    for name, value in properties:
        prop = getattr(cv2, name, None)
        if prop is not None:
            try:
                cap.set(prop, value)
            except Exception:
                pass

    actual = {}
    for key, name in (
        ("width", "CAP_PROP_FRAME_WIDTH"),
        ("height", "CAP_PROP_FRAME_HEIGHT"),
        ("fps", "CAP_PROP_FPS"),
    ):
        prop = getattr(cv2, name, None)
        try:
            actual[key] = float(cap.get(prop)) if prop is not None else 0.0
        except Exception:
            actual[key] = 0.0
    return actual
