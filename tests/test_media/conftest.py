"""Shared fakes for the media tests: an in-memory switch store and request builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bayram.media.contracts import MediaRequest


@dataclass
class MemorySwitchStore:
    """``MediaSwitchStore`` over a dict. ``fail`` makes every call raise, like a dead Redis."""

    values: dict[str, Any] = field(default_factory=dict)
    fail: bool = False

    async def get(self, name: str) -> Any:
        if self.fail:
            raise ConnectionError("redis is down")
        return self.values.get(name)

    async def set(self, name: str, value: str) -> Any:
        if self.fail:
            raise ConnectionError("redis is down")
        self.values[name] = value.encode()
        return True

    async def delete(self, *names: str) -> Any:
        if self.fail:
            raise ConnectionError("redis is down")
        for name in names:
            self.values.pop(name, None)
        return len(names)


def image_request(**overrides: Any) -> MediaRequest:
    values: dict[str, Any] = {
        "kind": "image",
        "model_key": "flux2",
        "prompt": "a lantern-lit courtyard in Samarkand at dusk",
        "refs": (),
        "width": 768,
        "height": 1344,
        "length_frames": None,
        "fps": None,
        "steps": 20,
        "seed": 7,
        "denoise": None,
    }
    values.update(overrides)
    return MediaRequest(**values)


def video_request(**overrides: Any) -> MediaRequest:
    values: dict[str, Any] = {
        "kind": "video",
        "model_key": "wan",
        "prompt": "a paper boat drifting down a canal",
        "refs": (),
        "width": 720,
        "height": 1280,
        "length_frames": 81,
        "fps": 16,
        "steps": 20,
        "seed": 11,
        "denoise": None,
    }
    values.update(overrides)
    return MediaRequest(**values)


def jpeg_file(directory: Path, name: str = "ref.jpg") -> Path:
    """A real, tiny JPEG on disk."""
    from PIL import Image

    path = directory / name
    Image.new("RGB", (32, 32), (200, 10, 10)).save(path, format="JPEG")
    return path
