from __future__ import annotations

from collections.abc import Callable


class LeagueWorkspaceContext:
    """One selected league or tournament shared by related application views."""

    def __init__(self, competition_id: str = "") -> None:
        self._competition_id = competition_id
        self._listeners: list[Callable[[str], None]] = []

    @property
    def competition_id(self) -> str:
        return self._competition_id

    def select(self, competition_id: str) -> None:
        clean_id = competition_id.strip()
        if clean_id == self._competition_id:
            return
        self._competition_id = clean_id
        for listener in tuple(self._listeners):
            listener(clean_id)

    def subscribe(
        self, listener: Callable[[str], None], *, notify: bool = False
    ) -> Callable[[], None]:
        if listener not in self._listeners:
            self._listeners.append(listener)
        if notify:
            listener(self._competition_id)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe


class ScoreSheetEditLocks:
    """Coordinates modal score editing across views in one app process."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def acquire(self, session_id: str, owner_id: str) -> bool:
        owner = self._owners.get(session_id)
        if owner not in (None, owner_id):
            return False
        self._owners[session_id] = owner_id
        return True

    def release(self, session_id: str, owner_id: str) -> None:
        if self._owners.get(session_id) == owner_id:
            del self._owners[session_id]
