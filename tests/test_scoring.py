import sqlite3
from decimal import Decimal

import pytest

from usbc_average_lookup.models import LookupResult, LookupStatus
from usbc_average_lookup.services.average_rules import AverageRounding
from usbc_average_lookup.services.registration import (
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
    RosterRole,
)
from usbc_average_lookup.services.scoring import (
    GameStatus,
    ScoringStore,
    SessionStatus,
)


def league_with_roster(tmp_path):
    path = tmp_path / "bowling-manager.db"
    registrations = RegistrationStore(path)
    league = registrations.add_competition(
        "Monday Misfits", "2026-27", CompetitionKind.LEAGUE
    )
    registrations.update_competition_scoring_settings(
        league.id,
        games_per_session=3,
        average_rule_name="90 percent composite",
        average_minimum_games=0,
        average_multiplier=Decimal("0.9"),
        average_add_pins=0,
        average_rounding=AverageRounding.NEAREST,
        handicap_base=200,
        handicap_percent=Decimal("0.9"),
        blind_penalty=10,
        vacancy_score=120,
    )
    team = registrations.add_team(league.id, "Pin Pals")
    player = registrations.register_bowler(
        league.id, "Player One", "1111-222222", team.id
    )
    registrations.apply_lookup_result(
        player.id,
        LookupResult(
            input_name="Player One",
            status=LookupStatus.FOUND,
            membership_id="1111-222222",
            average=180,
            year="2025",
            games=60,
        ),
    )
    substitute = registrations.register_bowler(
        league.id,
        "Sub Player",
        "3333-444444",
        roster_role=RosterRole.SUBSTITUTE,
    )
    return registrations, league, team, player, substitute


def test_session_keeps_player_team_and_rule_snapshots(tmp_path) -> None:
    registrations, league, team, player, _substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)

    session = scoring.create_session(league.id, 1, "2026-09-07", "Opening night")
    sheet = scoring.score_sheet(session.id)

    assert session.games_per_player == 3
    assert len(sheet) == 1
    assert sheet[0].line.player_name == "Player One"
    assert sheet[0].line.team_name == "Pin Pals"
    assert sheet[0].line.entering_average == 162
    assert sheet[0].line.handicap == 34
    assert len(sheet[0].games) == 3

    registrations.rename_team(team.id, "Renamed Later")
    registrations.update_bowler_profile(player.bowler_id, "Changed Later", "1111-222222")
    reopened_sheet = ScoringStore(RegistrationStore(registrations.path)).score_sheet(
        session.id
    )

    assert reopened_sheet[0].line.player_name == "Player One"
    assert reopened_sheet[0].line.team_name == "Pin Pals"


def test_team_totals_are_derived_from_player_scores(tmp_path) -> None:
    registrations, league, team, _player, substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)
    scoring.add_registered_player(session.id, substitute.id, team.id)
    first, second = scoring.score_sheet(session.id)

    scoring.save_line_scores(
        first.line.id,
        first.line.entering_average,
        [(GameStatus.BOWLED, 150), (GameStatus.BLIND, None), (GameStatus.ABSENT, None)],
    )
    scoring.save_line_scores(
        second.line.id,
        170,
        [(GameStatus.BOWLED, 170), (GameStatus.BOWLED, 180), (GameStatus.BOWLED, 190)],
    )

    totals = scoring.team_totals(session.id)[0]
    assert totals.scratch == (320, 332, 190)
    assert totals.counted == (381, 393, 217)
    assert totals.counted_total == 991


def test_vacancies_are_saved_for_every_game(tmp_path) -> None:
    registrations, league, team, _player, _substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)

    scoring.add_vacancy(session.id, team.id)
    vacancy = next(view for view in scoring.score_sheet(session.id) if view.line.is_vacancy)

    assert [game.status for game in vacancy.games] == [GameStatus.VACANCY] * 3
    assert [game.scratch_score for game in vacancy.games] == [120, 120, 120]
    assert [game.pins_counted for game in vacancy.games] == [192, 192, 192]


def test_score_correction_requires_reason_and_keeps_change_log(tmp_path) -> None:
    registrations, league, _team, _player, _substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)
    line = scoring.score_sheet(session.id)[0].line
    initial = [(GameStatus.BOWLED, 150)] * 3
    scoring.save_line_scores(line.id, line.entering_average, initial)

    with pytest.raises(RegistrationDataError, match="reason"):
        scoring.save_line_scores(
            line.id,
            line.entering_average,
            [(GameStatus.BOWLED, 151), *initial[1:]],
        )

    scoring.save_line_scores(
        line.id,
        line.entering_average,
        [(GameStatus.BOWLED, 151), *initial[1:]],
        "Corrected from the recap sheet",
    )

    changes = scoring.change_log(session.id)
    assert len(changes) == 1
    assert changes[0].game_number == 1
    assert changes[0].old_scratch_score == 150
    assert changes[0].new_scratch_score == 151
    assert changes[0].reason == "Corrected from the recap sheet"


def test_history_can_be_filtered_from_league_to_team(tmp_path) -> None:
    registrations, league, first_team, _player, _substitute = league_with_roster(
        tmp_path
    )
    second_team = registrations.add_team(league.id, "Other Team")
    registrations.register_bowler(
        league.id, "Other Player", "5555-666666", second_team.id
    )
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)
    for view in scoring.score_sheet(session.id):
        scoring.save_line_scores(
            view.line.id,
            view.line.entering_average,
            [(GameStatus.BOWLED, 100)] * 3,
        )

    league_summary = scoring.session_history(league.id)[0]
    team_summary = scoring.session_history(league.id, first_team.id)[0]

    assert league_summary.player_rows == 2
    assert league_summary.scratch_total == 600
    assert team_summary.player_rows == 1
    assert team_summary.scratch_total == 300


def test_removing_scored_player_requires_reason_and_is_logged(tmp_path) -> None:
    registrations, league, team, _player, substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)
    scoring.add_registered_player(session.id, substitute.id, team.id)
    substitute_line = next(
        view
        for view in scoring.score_sheet(session.id)
        if view.line.registration_id == substitute.id
    )
    scoring.save_line_scores(
        substitute_line.line.id,
        170,
        [(GameStatus.BOWLED, 170)] * 3,
    )

    with pytest.raises(RegistrationDataError, match="reason"):
        scoring.remove_line(substitute_line.line.id)

    scoring.remove_line(substitute_line.line.id, "Substitute was entered on wrong team")

    changes = scoring.change_log(session.id)
    assert len(changes) == 3
    assert {change.team_id for change in changes} == {team.id}
    assert {change.new_status for change in changes} == {"Removed"}


def test_removed_regular_can_be_added_back_with_original_role(tmp_path) -> None:
    registrations, league, team, player, _substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)
    regular_line = scoring.score_sheet(session.id)[0].line

    scoring.remove_line(regular_line.id)
    assert scoring.score_sheet(session.id) == []

    scoring.add_registered_player(session.id, player.id, team.id)
    restored = scoring.score_sheet(session.id)[0]

    assert restored.line.registration_id == player.id
    assert restored.line.roster_role is RosterRole.REGULAR
    assert restored.line.team_id == team.id


def test_final_score_sheet_requires_complete_games_and_reopen_reason(tmp_path) -> None:
    registrations, league, _team, _player, _substitute = league_with_roster(tmp_path)
    scoring = ScoringStore(registrations)
    session = scoring.create_session(league.id, 1)
    line = scoring.score_sheet(session.id)[0].line

    with pytest.raises(RegistrationDataError, match="missing"):
        scoring.finalize_session(session.id)

    scoring.save_line_scores(
        line.id,
        line.entering_average,
        [(GameStatus.BOWLED, 150)] * 3,
    )
    scoring.finalize_session(session.id)
    assert scoring.get_session(session.id).status is SessionStatus.FINAL

    with pytest.raises(RegistrationDataError, match="reason"):
        scoring.reopen_session(session.id, "")

    scoring.reopen_session(session.id, "League secretary approved correction")
    assert scoring.get_session(session.id).status is SessionStatus.DRAFT
    changes = scoring.change_log(session.id)
    assert changes[0].old_status == SessionStatus.FINAL
    assert changes[0].new_status == SessionStatus.DRAFT


def test_schema_one_database_is_backed_up_and_upgraded(tmp_path) -> None:
    path = tmp_path / "bowling-manager.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE player_pools (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE bowlers (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                membership_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE competitions (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, season TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL, created_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0, player_pool_id TEXT
            );
            CREATE TABLE teams (
                id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, name TEXT NOT NULL
            );
            CREATE TABLE player_pool_entries (
                pool_id TEXT NOT NULL, bowler_id TEXT NOT NULL,
                PRIMARY KEY (pool_id, bowler_id)
            );
            CREATE TABLE registrations (
                id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, bowler_id TEXT NOT NULL,
                team_id TEXT, roster_role TEXT NOT NULL DEFAULT 'Regular',
                verification TEXT NOT NULL DEFAULT 'Not checked', average INTEGER,
                average_year TEXT NOT NULL DEFAULT '', games INTEGER,
                note TEXT NOT NULL DEFAULT '', withdrawn INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO competitions (
                id, name, season, kind, created_at, archived
            ) VALUES ('league-1', 'Monday', '2026-27', 'League', 'now', 0);
            PRAGMA user_version = 1;
            """
        )

    upgraded = RegistrationStore(path)

    assert upgraded.competitions[0].games_per_session == 3
    assert path.with_name("bowling-manager.schema-v1-backup.db").exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'score_change_log'"
        ).fetchone()


def test_schema_two_change_log_is_upgraded_with_team_identity(tmp_path) -> None:
    path = tmp_path / "bowling-manager.db"
    store = RegistrationStore(path)
    store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE score_change_log DROP COLUMN team_id")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()

    RegistrationStore(path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(score_change_log)")
        }
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert "team_id" in columns
    assert path.with_name("bowling-manager.schema-v2-backup.db").exists()
