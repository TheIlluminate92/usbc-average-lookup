from queue import Queue

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
