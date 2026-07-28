"""Narrow command/snapshot boundary between tool workers and the Qt UI."""

from __future__ import annotations

from typing import Any, Protocol


class _UiCommandTarget(Protocol):
    @property
    def current_file(self) -> str | None: ...

    @property
    def microphone_enabled(self) -> bool: ...

    @property
    def listen_mode(self) -> str: ...

    def write_log(self, text: str) -> None: ...
    def show_study_result(self, artifact: dict | None, automatic: bool = True) -> str: ...
    def show_content(self, title: str, text: str) -> None: ...
    def show_memory_graph(self) -> None: ...
    def refresh_memory_graph(self) -> None: ...
    def show_geo(self, place: dict | None = None) -> None: ...
    def enter_pet_mode(self, state: str, message: str) -> None: ...
    def control_interface(self, action: str, target: str, mode: str = "") -> Any: ...


class UiCommandFacade:
    """Expose only queued UI commands and immutable state snapshots to workers."""

    __slots__ = ("_target",)

    def __init__(self, target: _UiCommandTarget):
        self._target = target

    @property
    def current_file(self) -> str | None:
        return self._target.current_file

    @property
    def microphone_enabled(self) -> bool:
        return self._target.microphone_enabled

    @property
    def listen_mode(self) -> str:
        return self._target.listen_mode

    def write_log(self, text: str) -> None:
        self._target.write_log(text)

    def show_study_result(self, artifact: dict | None, automatic: bool = True) -> str:
        return self._target.show_study_result(artifact, automatic=automatic)

    def show_content(self, title: str, text: str) -> None:
        self._target.show_content(title, text)

    def show_memory_graph(self) -> None:
        self._target.show_memory_graph()

    def refresh_memory_graph(self) -> None:
        self._target.refresh_memory_graph()

    def show_geo(self, place: dict | None = None) -> None:
        self._target.show_geo(place)

    def enter_pet_mode(self, state: str, message: str) -> None:
        self._target.enter_pet_mode(state, message)

    def control_interface(self, action: str, target: str, mode: str = "") -> Any:
        return self._target.control_interface(action, target, mode)
