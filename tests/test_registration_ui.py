from queue import Queue

from usbc_average_lookup import registration_ui
from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.registration_ui import RegistrationDesk
from usbc_average_lookup.services.registration import (
    CompetitionKind,
    RegistrationStore,
    VerificationState,
)


def test_selected_match_refreshes_player_and_team_management(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.db")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    registration = store.register_bowler(competition.id, "David Brown")
    desk = RegistrationDesk.__new__(RegistrationDesk)
    desk.store = store
    desk.lookup_results = {}
    desk.bulk_pending = set()
    refreshed: list[str] = []
    statuses: list[str] = []
    desk._render_rows = lambda: refreshed.append("registration")
    desk._render_players = lambda: refreshed.append("players")
    desk._render_teams = lambda: refreshed.append("teams")
    desk.status_callback = statuses.append

    desk._lookup_finished(
        registration.id,
        LookupResult(
            input_name="David Brown",
            status=LookupStatus.FOUND,
            membership_id="1234-567890",
            average=181,
            year="2025",
            games=60,
        ),
        "Match confirmed",
    )

    assert store.bowlers[0].membership_id == "1234-567890"
    assert refreshed == ["registration", "players", "teams"]
    assert statuses == ["Match confirmed"]


def test_starting_lookup_refreshes_team_roster_status(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.db")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    registration = store.register_bowler(competition.id, "David Brown")
    desk = RegistrationDesk.__new__(RegistrationDesk)
    desk.store = store
    desk.api_provider = object
    desk.lookup_queue = Queue()
    refreshed: list[str] = []
    statuses: list[str] = []
    desk._render_rows = lambda: refreshed.append("registration")
    desk._render_teams = lambda: refreshed.append("teams")
    desk.status_callback = statuses.append

    desk._queue_lookups(
        [(registration.id, InputBowler("David Brown", ""))]
    )

    assert registration.verification is VerificationState.CHECKING
    assert refreshed == ["registration", "teams"]
    assert desk.lookup_queue.qsize() == 1
    assert statuses == ["Checking David Brown…"]


def test_failed_bulk_lookup_start_clears_progress(tmp_path, monkeypatch) -> None:
    store = RegistrationStore(tmp_path / "registration.db")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    registration = store.register_bowler(competition.id, "David Brown")
    desk = RegistrationDesk.__new__(RegistrationDesk)
    desk.store = store
    desk.api_provider = object
    desk.lookup_queue = Queue()
    desk.bulk_pending = {registration.id}
    statuses: list[str] = []
    errors: list[str] = []
    desk.status_callback = statuses.append
    monkeypatch.setattr(
        store,
        "mark_checking_many",
        lambda _registration_ids: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        registration_ui.messagebox,
        "showerror",
        lambda _title, message, **_kwargs: errors.append(message),
    )

    desk._queue_lookups([(registration.id, InputBowler("David Brown", ""))])

    assert desk.bulk_pending == set()
    assert desk.lookup_queue.empty()
    assert statuses == ["Registration checks stopped"]
    assert errors == ["disk full"]


def test_failed_identity_match_leaves_lookup_in_reviewable_state(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    store.register_bowler(competition.id, "David Brown", "1111-222222")
    pending = store.register_bowler(
        competition.id, "David Brown", "3333-444444"
    )
    store.mark_checking(pending.id)
    desk = RegistrationDesk.__new__(RegistrationDesk)
    desk.store = store
    desk.lookup_results = {}
    desk.bulk_pending = {pending.id}
    refreshed: list[str] = []
    statuses: list[str] = []
    errors: list[str] = []
    desk._render_rows = lambda: refreshed.append("registration")
    desk._render_players = lambda: refreshed.append("players")
    desk._render_teams = lambda: refreshed.append("teams")
    desk.status_callback = statuses.append
    monkeypatch.setattr(
        registration_ui.messagebox,
        "showerror",
        lambda _title, message, **_kwargs: errors.append(message),
    )

    desk._lookup_finished(
        pending.id,
        LookupResult(
            input_name="David Brown",
            status=LookupStatus.FOUND,
            membership_id="1111-222222",
            average=181,
        ),
        "Match confirmed",
    )

    view = next(
        item
        for item in store.registration_views(competition.id)
        if item.registration.id == pending.id
    )
    assert view.registration.verification is VerificationState.ERROR
    assert "already registered" in view.registration.note
    assert desk.bulk_pending == set()
    assert refreshed == ["registration", "players", "teams"]
    assert statuses == ["Registration checks complete"]
    assert len(errors) == 1
    reopened = RegistrationStore(path)
    reopened_view = next(
        item
        for item in reopened.registration_views(competition.id)
        if item.registration.id == pending.id
    )
    assert reopened_view.registration.verification is VerificationState.ERROR
