import sqlite3

import pytest

from usbc_average_lookup.services.registration import (
    CompetitionFormat,
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
)
from usbc_average_lookup.services.scheduling import ScheduleStore


def competition_with_teams(tmp_path, count: int):
    registrations = RegistrationStore(tmp_path / "bowling-manager.db")
    competition = registrations.add_competition(
        "Monday",
        "2026-27",
        CompetitionKind.LEAGUE,
        CompetitionFormat.ROUND_ROBIN,
    )
    teams = [
        registrations.add_team(competition.id, f"Team {number:02d}")
        for number in range(1, count + 1)
    ]
    return registrations, competition, teams


def test_twenty_team_round_robin_pairs_every_team_once(tmp_path) -> None:
    registrations, competition, teams = competition_with_teams(tmp_path, 20)
    schedules = ScheduleStore(registrations)

    rounds = schedules.generate_round_robin(competition.id, first_lane=5)

    assert len(rounds) == 19
    seen_pairs: set[frozenset[str]] = set()
    for round_ in rounds:
        matches = schedules.list_matches(round_.id)
        assert len(matches) == 10
        round_teams = [
            team_id
            for match in matches
            for team_id in (match.left_team_id, match.right_team_id)
            if team_id
        ]
        assert len(round_teams) == len(set(round_teams)) == 20
        lanes = [match.lane_start for match in matches]
        assert len(lanes) == len(set(lanes)) == 10
        assert min(lanes) == 5
        assert max(lanes) == 23
        seen_pairs.update(
            frozenset((match.left_team_id, match.right_team_id))
            for match in matches
        )

    assert len(seen_pairs) == len(teams) * (len(teams) - 1) // 2


def test_odd_team_schedule_has_one_explicit_bye_per_round(tmp_path) -> None:
    registrations, competition, teams = competition_with_teams(tmp_path, 5)
    schedules = ScheduleStore(registrations)

    rounds = schedules.generate_round_robin(competition.id)

    assert len(rounds) == 5
    bye_teams: list[str] = []
    for round_ in rounds:
        matches = schedules.list_matches(round_.id)
        byes = [match for match in matches if match.is_bye]
        assert len(byes) == 1
        assert byes[0].lane_start is None
        bye_teams.append(byes[0].left_team_id)
    assert set(bye_teams) == {team.id for team in teams}


def test_schedule_survives_restart_and_lane_can_be_changed(tmp_path) -> None:
    path = tmp_path / "bowling-manager.db"
    registrations, competition, _teams = competition_with_teams(tmp_path, 4)
    schedules = ScheduleStore(registrations)
    first_round = schedules.generate_round_robin(competition.id)[0]
    matches = schedules.list_matches(first_round.id)

    schedules.update_match_lane(matches[0].id, 21)

    reopened = RegistrationStore(path)
    reopened_schedule = ScheduleStore(reopened)
    saved = reopened_schedule.list_matches(first_round.id)
    assert any(match.id == matches[0].id and match.lane_start == 21 for match in saved)


def test_live_roster_edits_do_not_rewrite_historical_schedule_names(tmp_path) -> None:
    registrations, competition, teams = competition_with_teams(tmp_path, 4)
    schedules = ScheduleStore(registrations)
    first_round = schedules.generate_round_robin(competition.id)[0]
    original_names = {
        name
        for match in schedules.list_matches(first_round.id)
        for name in (match.left_team_name, match.right_team_name)
        if name
    }

    registrations.rename_team(teams[0].id, "Renamed Team")

    saved_names = {
        name
        for match in schedules.list_matches(first_round.id)
        for name in (match.left_team_name, match.right_team_name)
        if name
    }
    assert saved_names == original_names


def test_schedule_rejects_duplicate_generation_and_duplicate_lanes(tmp_path) -> None:
    registrations, competition, _teams = competition_with_teams(tmp_path, 4)
    schedules = ScheduleStore(registrations)
    first_round = schedules.generate_round_robin(competition.id)[0]
    matches = schedules.list_matches(first_round.id)

    with pytest.raises(RegistrationDataError, match="already has a schedule"):
        schedules.generate_round_robin(competition.id)
    with pytest.raises(RegistrationDataError, match="already assigned"):
        schedules.update_match_lane(matches[0].id, matches[1].lane_start)


def test_non_round_robin_format_is_not_generated_as_round_robin(tmp_path) -> None:
    registrations = RegistrationStore(tmp_path / "bowling-manager.db")
    competition = registrations.add_competition(
        "Elimination Open",
        "2027",
        CompetitionKind.TOURNAMENT,
        CompetitionFormat.SINGLE_ELIMINATION,
    )
    registrations.add_team(competition.id, "One")
    registrations.add_team(competition.id, "Two")

    with pytest.raises(RegistrationDataError, match="Round robin"):
        ScheduleStore(registrations).generate_round_robin(competition.id)


def test_schema_three_database_is_backed_up_and_upgraded(tmp_path) -> None:
    path = tmp_path / "bowling-manager.db"
    RegistrationStore(path).add_competition(
        "Monday", "2026-27", CompetitionKind.LEAGUE
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            DROP TABLE competition_matches;
            DROP TABLE competition_rounds;
            ALTER TABLE competitions DROP COLUMN competition_format;
            PRAGMA user_version = 3;
            """
        )

    upgraded = RegistrationStore(path)

    assert upgraded.competitions[0].competition_format is CompetitionFormat.ROUND_ROBIN
    assert path.with_name("bowling-manager.schema-v3-backup.db").exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'competition_matches'"
        ).fetchone()
