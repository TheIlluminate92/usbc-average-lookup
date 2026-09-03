import sqlite3
from decimal import Decimal
from unittest.mock import Mock

import pytest

from usbc_average_lookup.services.registration import (
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
)
from usbc_average_lookup.services.scheduling import ScheduleStore
from usbc_average_lookup.services.scoring import GameStatus, ScoringStore
from usbc_average_lookup.services.standings import StandingRules, StandingsStore


def fixture(tmp_path, count=2, kind=CompetitionKind.LEAGUE):
    registrations = RegistrationStore(tmp_path / "league.db")
    league = registrations.add_competition("Monday", "2026-27", kind)
    teams = [registrations.add_team(league.id, f"Team {i}") for i in range(count)]
    for i, team in enumerate(teams):
        registrations.register_bowler(league.id, f"Player {i}", team_id=team.id)
    schedules = ScheduleStore(registrations)
    rounds = schedules.generate_round_robin(league.id)
    scores = ScoringStore(registrations)
    week = scores.create_session(league.id, 1)
    results = StandingsStore(registrations)
    return registrations, league, teams, rounds, scores, week, results


def enter(scores, week, values):
    for line in scores.score_sheet(week.id):
        scores.save_line_scores(
            line.line.id, 150,
            [(GameStatus.BOWLED, score) for score in values[line.line.team_id]],
        )


def test_final_results_ties_and_corrections_recalculate(tmp_path):
    registrations, league, teams, rounds, scores, week, results = fixture(tmp_path)
    results.link(rounds[0].id, week.id)
    enter(scores, week, {teams[0].id: [150, 200, 100], teams[1].id: [100, 200, 200]})
    assert scores.linked_round_number(week.id) == 1
    assert all(s.points == 0 for s in results.standings(league.id))
    assert results.round_results(rounds[0].id)[0].status == "Draft — not counted"
    changed = Mock()
    registrations.add_change_listener(changed)
    scores.finalize_session(week.id)
    changed.assert_called_once()
    winner, loser = results.standings(league.id)
    assert winner.team_id == teams[1].id
    assert (winner.wins, winner.losses, winner.points) == (1, 0, Decimal("2.5"))
    assert (loser.game_wins, loser.game_ties, loser.points) == (1, 1, Decimal("1.5"))
    assert winner.scratch_pins == 500
    scores.reopen_session(week.id, "Correct paper recap")
    assert all(s.played == 0 for s in results.standings(league.id))
    first = next(v for v in scores.score_sheet(week.id) if v.line.team_id == teams[0].id)
    scores.save_line_scores(first.line.id, 150,
                           [(GameStatus.BOWLED, v) for v in [300, 200, 100]], "Paper recap")
    scores.finalize_session(week.id)
    assert results.standings(league.id)[0].team_id == teams[0].id
    assert any(c.reason == "Paper recap" for c in scores.change_log(week.id))
    restarted = StandingsStore(RegistrationStore(registrations.path))
    assert restarted.standings(league.id) == results.standings(league.id)


def test_rules_snapshot_and_idempotent_link(tmp_path):
    _, league, teams, rounds, scores, week, results = fixture(tmp_path)
    results.save_rules(league.id, StandingRules(game_points="2", series_points="4"))
    results.link(rounds[0].id, week.id)
    results.save_rules(league.id, StandingRules(game_points="10", series_points="10"))
    results.link(rounds[0].id, week.id)
    enter(scores, week, {teams[0].id: [200]*3, teams[1].id: [100]*3})
    scores.finalize_session(week.id)
    assert results.standings(league.id)[0].points == 10
    with pytest.raises(RegistrationDataError, match="Reopen"):
        results.unlink(rounds[0].id, "Wrong link")
    scores.reopen_session(week.id, "Wrong week")
    with pytest.raises(RegistrationDataError, match="reason"):
        results.unlink(rounds[0].id, " ")
    results.unlink(rounds[0].id, "Selected wrong week")
    assert results.linked_session(rounds[0].id) is None
    assert any(c.reason == "Selected wrong week" for c in scores.change_log(week.id))


def test_link_rejects_cross_league_and_reuse(tmp_path):
    registrations, league, _, rounds, scores, week, results = fixture(tmp_path, 4)
    other = registrations.add_competition("Other", "2026", CompetitionKind.LEAGUE)
    other_week = scores.create_session(other.id, 1)
    with pytest.raises(RegistrationDataError, match="same league"):
        results.link(rounds[0].id, other_week.id)
    results.link(rounds[0].id, week.id)
    with pytest.raises(RegistrationDataError, match="already linked"):
        results.link(rounds[1].id, week.id)
    week2 = scores.create_session(league.id, 2)
    with pytest.raises(RegistrationDataError, match="already has"):
        results.link(rounds[0].id, week2.id)


def test_missing_team_blocks_finalize_and_unrelated_team_blocks_link(tmp_path):
    registrations, league, teams, rounds, scores, week, results = fixture(tmp_path)
    results.link(rounds[0].id, week.id)
    line = scores.score_sheet(week.id)[0]
    scores.remove_line(line.line.id)
    remaining = scores.score_sheet(week.id)[0]
    scores.save_line_scores(remaining.line.id, 150, [(GameStatus.BOWLED, 0)]*3)
    with pytest.raises(RegistrationDataError, match="scheduled opponent"):
        scores.finalize_session(week.id)
    results.unlink(rounds[0].id, "Fix roster")
    extra = registrations.add_team(league.id, "New team after schedule")
    scores.add_vacancy(week.id, extra.id)
    with pytest.raises(RegistrationDataError, match="teams do not match"):
        results.link(rounds[0].id, week.id)


def test_bye_never_becomes_a_win_and_real_zero_is_a_tie(tmp_path):
    _, league, teams, rounds, scores, week, results = fixture(tmp_path, 3)
    results.link(rounds[0].id, week.id)
    enter(scores, week, {t.id: [0]*3 for t in teams})
    scores.finalize_session(week.id)
    standings = results.standings(league.id)
    assert sum(s.played for s in standings) == 2
    assert sum(s.wins for s in standings) == 0
    assert sum(s.points for s in standings) == 4
    assert {s.rank for s in standings} == {1}
    assert any(r.status == "BYE — no points" for r in results.round_results(rounds[0].id))


@pytest.mark.parametrize("comparison,winner", [("Scratch", 0), ("Handicap", 1)])
def test_scratch_and_handicap_comparison(tmp_path, comparison, winner):
    registrations, league, teams, rounds, scores, week, results = fixture(tmp_path)
    results.save_rules(league.id, StandingRules(comparison=comparison))
    results.link(rounds[0].id, week.id)
    enter(scores, week, {teams[0].id: [160]*3, teams[1].id: [150]*3})
    # Saved counted pins are the authoritative historical handicap contribution.
    with sqlite3.connect(registrations.path) as connection:
        connection.execute(
            "UPDATE game_scores SET pins_counted = 180 WHERE score_line_id IN "
            "(SELECT id FROM score_lines WHERE team_id = ?)", (teams[1].id,),
        )
    scores.finalize_session(week.id)
    assert results.standings(league.id)[0].team_id == teams[winner].id


def test_no_points_ties_and_explicit_pin_tiebreaker(tmp_path):
    _, league, teams, rounds, scores, week, results = fixture(tmp_path)
    results.save_rules(league.id, StandingRules(
        ties="No points", game_points="0", series_points="0",
        ranking="Points", tiebreaker="Scratch pins",
    ))
    results.link(rounds[0].id, week.id)
    enter(scores, week, {teams[0].id: [200, 100, 100], teams[1].id: [100, 100, 100]})
    scores.finalize_session(week.id)
    standings = results.standings(league.id)
    assert [s.rank for s in standings] == [1, 2]
    assert standings[0].team_id == teams[0].id
    assert all(s.points == 0 for s in standings)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "101", "bad"])
def test_invalid_point_rules(value):
    with pytest.raises(RegistrationDataError):
        StandingRules(game_points=value).validate()


def test_schema_four_backup_preserves_scores(tmp_path):
    registrations, league, _, rounds, scores, week, _ = fixture(tmp_path)
    with sqlite3.connect(registrations.path) as connection:
        connection.executescript(
            "DROP TABLE round_score_links; DROP TABLE standing_rules; PRAGMA user_version = 4;"
        )
    upgraded = RegistrationStore(registrations.path)
    assert upgraded.path.with_name("league.schema-v4-backup.db").exists()
    assert ScoringStore(upgraded).get_session(week.id) == week
    assert ScheduleStore(upgraded).list_rounds(league.id) == rounds
    with sqlite3.connect(upgraded.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_lane_pairs_cannot_overlap_by_one_lane(tmp_path):
    registrations, _, _, rounds, _, _, results = fixture(tmp_path, 4)
    match = results.schedules.list_matches(rounds[0].id)[0]
    with pytest.raises(RegistrationDataError, match="already assigned"):
        ScheduleStore(registrations).update_match_lane(match.id, 2)


def test_open_scores_selects_exact_linked_session(tmp_path):
    from usbc_average_lookup.scoring_ui import ScoringDesk

    _, league, _, _, scores, week, _ = fixture(tmp_path)
    desk = ScoringDesk.__new__(ScoringDesk)
    desk.scoring_store = scores
    desk.workspace_context = Mock()
    desk.refresh = Mock()
    desk.session_var = Mock()
    desk.team_filter_var = Mock()
    desk._session_changed = Mock()
    desk.open_session(week.id)
    desk.workspace_context.select.assert_called_once_with(league.id)
    desk.session_var.set.assert_called_once_with(week.display_name)
    desk.team_filter_var.set.assert_called_once_with("All teams")
    desk._session_changed.assert_called_once()


def test_invalid_rules_dialog_keeps_cancel_available(monkeypatch):
    from usbc_average_lookup.standings_ui import RulesDialog

    dialog = RulesDialog.__new__(RulesDialog)
    dialog.variables = {key: Mock(get=Mock(return_value=value)) for key, value in {
        "comparison": "Handicap", "game_points": "NaN", "series_points": "1",
        "ties": "Split points", "ranking": "Series wins", "tiebreaker": "None",
    }.items()}
    dialog.save_callback = Mock()
    dialog.error = Mock()
    dialog.destroy = Mock()
    monkeypatch.setattr("usbc_average_lookup.standings_ui.messagebox.showwarning", Mock())
    dialog._save()
    dialog.destroy.assert_not_called()
    dialog.save_callback.assert_not_called()
    dialog.error.configure.assert_called_once()


def test_round_robin_tournament_can_be_scored(tmp_path):
    _, league, teams, rounds, scores, week, results = fixture(
        tmp_path, kind=CompetitionKind.TOURNAMENT,
    )
    results.link(rounds[0].id, week.id)
    enter(scores, week, {t.id: [100, 100, 100] for t in teams})
    scores.finalize_session(week.id)
    assert all(s.ties == 1 for s in results.standings(league.id))


def test_unlinked_final_scores_are_not_counted(tmp_path):
    _, league, teams, rounds, scores, week, results = fixture(tmp_path)
    enter(scores, week, {t.id: [150]*3 for t in teams})
    scores.finalize_session(week.id)
    assert all(s.played == 0 for s in results.standings(league.id))
    with pytest.raises(RegistrationDataError, match="Reopen"):
        results.link(rounds[0].id, week.id)
