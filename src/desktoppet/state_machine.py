"""UI-independent state machine for the desktop pet."""

from __future__ import annotations

from enum import Enum
from typing import Callable


class PetState(str, Enum):
    IDLE = "idle"
    HOVER = "hover"
    LOADING = "loading"
    WORKING = "working"


class PetEvent(str, Enum):
    HOVER_ENTER = "hover_enter"
    HOVER_LEAVE = "hover_leave"
    LOAD_STARTED = "load_started"
    WORK_STARTED = "work_started"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"


StateListener = Callable[[PetState, PetState], None]


class PetStateMachine:
    """Resolve task and pointer signals into one visible pet state."""

    def __init__(self) -> None:
        self._state = PetState.IDLE
        self._pointer_inside = False
        self._activity: PetState | None = None
        self._listeners: list[StateListener] = []

    @property
    def state(self) -> PetState:
        return self._state

    @property
    def pointer_inside(self) -> bool:
        return self._pointer_inside

    def subscribe(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def dispatch(self, event: PetEvent) -> PetState:
        if event is PetEvent.HOVER_ENTER:
            self._pointer_inside = True
        elif event is PetEvent.HOVER_LEAVE:
            self._pointer_inside = False
        elif event is PetEvent.LOAD_STARTED:
            self._activity = PetState.LOADING
        elif event is PetEvent.WORK_STARTED:
            self._activity = PetState.WORKING
        elif event in {PetEvent.FINISHED, PetEvent.CANCELLED, PetEvent.FAILED}:
            self._activity = None

        target = self._activity or (
            PetState.HOVER if self._pointer_inside else PetState.IDLE
        )
        self._set_state(target)
        return self._state

    def force(self, state: PetState) -> PetState:
        """Set a state from the prototype debug menu."""
        self._activity = state if state in {PetState.LOADING, PetState.WORKING} else None
        self._pointer_inside = state is PetState.HOVER
        self._set_state(state)
        return self._state

    def _set_state(self, target: PetState) -> None:
        if target is self._state:
            return
        previous = self._state
        self._state = target
        for listener in tuple(self._listeners):
            listener(previous, target)
