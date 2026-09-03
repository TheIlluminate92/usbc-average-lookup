import sqlite3
from unittest.mock import Mock

import pytest

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.services.registration import (
    BowlerProfile,
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
)
from usbc_average_lookup.services.scheduling import ScheduleStore
from usbc_average_lookup.services.scoring import GameStatus, ScoringStore
from usbc_average_lookup.services.standings import StandingsStore


def setup(tmp_path):
    store = RegistrationStore(tmp_path / "test.db")
    league = store.add_competition("Monday", "2026", CompetitionKind.LEAGUE)
    team = store.add_team(league.id, "A")
    player = BowlerProfile("player", "Test Player")
    store.bowlers.append(player)
    store.save()
    return store, league, team, player


def test_empty_records_delete_without_touching_parent_league(tmp_path):
    store, league, team, player = setup(tmp_path)
    changed = Mock()
    store.add_change_listener(changed)
    store.delete_player(player.id)
    store.delete_team(team.id)
    store.save()
    restarted = RegistrationStore(store.path)
    assert restarted.bowlers == []
    assert restarted.teams == []
    assert restarted.competitions[0].id == league.id
    assert changed.call_count == 3


@pytest.mark.parametrize("withdrawn", [False, True])
def test_registrations_block_player_and_team_even_when_withdrawn(tmp_path, withdrawn):
    store, league, team, player = setup(tmp_path)
    reg = store.register_bowler(league.id, player.name, team_id=team.id)
    store.set_withdrawn(reg.id, withdrawn)
    for kind, entity_id in (("player", player.id), ("team", team.id)):
        assert "registrations" in store.deletion_blockers(kind, entity_id)
        with pytest.raises(RegistrationDataError, match="registrations"):
            (store.delete_player if kind == "player" else store.delete_team)(entity_id)
    assert len(RegistrationStore(store.path).registrations) == 1


def test_pool_entry_alone_blocks_player_delete(tmp_path):
    store, _, _, player = setup(tmp_path)
    pool = store.add_player_pool("2026")
    store.add_bowler_to_pool(pool.id, player.id)
    with pytest.raises(RegistrationDataError, match="season-pool"):
        store.delete_player(player.id)


def test_matchup_alone_blocks_empty_team_delete(tmp_path):
    store, league, team, _ = setup(tmp_path)
    store.add_team(league.id, "B")
    ScheduleStore(store).generate_round_robin(league.id)
    with pytest.raises(RegistrationDataError, match="scheduled matchups"):
        store.delete_team(team.id)


def test_score_snapshot_and_removed_row_history_block_delete(tmp_path):
    store, league, team, player = setup(tmp_path)
    store.register_bowler(league.id, player.name, team_id=team.id)
    scoring = ScoringStore(store)
    week = scoring.create_session(league.id, 1)
    line = scoring.score_sheet(week.id)[0].line
    scoring.save_line_scores(line.id, 150, [(GameStatus.BOWLED, 150)]*3)
    # Simulate a legacy record without its registration; snapshots still protect it.
    store.registrations.clear()
    store.save()
    for kind, entity_id in (("player", player.id), ("team", team.id)):
        assert "score sheets" in store.deletion_blockers(kind, entity_id)
    scoring.remove_line(line.id, "Entered on wrong sheet")
    store.update_bowler_profile(player.id, "Renamed Player", "")
    for kind, entity_id in (("player", player.id), ("team", team.id)):
        assert "score history" in store.deletion_blockers(kind, entity_id)
        with pytest.raises(RegistrationDataError, match="score history"):
            (store.delete_player if kind == "player" else store.delete_team)(entity_id)


def test_archive_restore_preserves_scores_standings_and_registrations(tmp_path):
    store, league, team, player = setup(tmp_path)
    second = store.add_team(league.id, "B")
    store.register_bowler(league.id, player.name, team_id=team.id)
    store.register_bowler(league.id, "Opponent", team_id=second.id)
    round_ = ScheduleStore(store).generate_round_robin(league.id)[0]
    scoring = ScoringStore(store)
    week = scoring.create_session(league.id, 1)
    for view in scoring.score_sheet(week.id):
        scoring.save_line_scores(view.line.id, 150, [(GameStatus.BOWLED, 150)]*3)
    standings = StandingsStore(store)
    standings.link(round_.id, week.id)
    scoring.finalize_session(week.id)
    original = standings.standings(league.id)
    sheet = scoring.score_sheet(week.id)
    store.set_player_archived(player.id, True)
    store.set_team_archived(team.id, True)
    assert len(store.registrations) == 2
    assert standings.standings(league.id) == original
    assert scoring.score_sheet(week.id) == sheet
    assert team.id not in {t.id for t in store.list_teams(league.id)}
    restarted = RegistrationStore(store.path)
    assert restarted._bowler(player.id).archived
    assert restarted._team(team.id).archived
    next_week = scoring.create_session(league.id, 2)
    assert {v.line.team_id for v in scoring.score_sheet(next_week.id)} == {second.id}
    store.set_player_archived(player.id, False)
    store.set_team_archived(team.id, False)
    assert team.id in {t.id for t in store.list_teams(league.id)}


def test_archived_records_cannot_be_used_for_new_registration(tmp_path):
    store, league, team, player = setup(tmp_path)
    store.set_player_archived(player.id, True)
    with pytest.raises(RegistrationDataError, match="archived player"):
        store.register_bowler(league.id, player.name)
    store.set_player_archived(player.id, False)
    store.set_team_archived(team.id, True)
    with pytest.raises(RegistrationDataError, match="archived team"):
        store.register_bowler(league.id, player.name, team_id=team.id)
    with pytest.raises(RegistrationDataError, match="archived team"):
        store.register_team(league.id, team.name, [InputBowler(name="Another")])
    assert len(store.teams) == 1
    assert store.registrations == []


def test_lookup_identity_merge_preserves_old_score_profile(tmp_path):
    store, league, team, player = setup(tmp_path)
    reg = store.register_bowler(league.id, player.name, team_id=team.id)
    scores = ScoringStore(store)
    week = scores.create_session(league.id, 1)
    target = BowlerProfile("target", "Same Person", "1234-567890")
    store.bowlers.append(target)
    store.save()
    store.apply_lookup_result(reg.id, LookupResult(
        input_name=player.name, status=LookupStatus.FOUND, membership_id=target.membership_id,
        average=150, year="2026", games=30,
    ))
    assert store._bowler(player.id).archived
    assert store._registration(reg.id).bowler_id == target.id
    assert scores.score_sheet(week.id)[0].line.bowler_id == player.id


def test_archived_player_cannot_change_teams_or_be_copied(tmp_path):
    store, league, team, player = setup(tmp_path)
    reg = store.register_bowler(league.id, player.name, team_id=team.id)
    second = store.add_team(league.id, "B")
    store.set_player_archived(player.id, True)
    with pytest.raises(RegistrationDataError, match="archived player"):
        store.update_registration(reg.id, player.name, "", second.id)
    next_league = store.add_competition("Next", "2027", CompetitionKind.LEAGUE)
    _, copied, skipped = store.copy_team_to_competition(team.id, next_league.id, "A")
    assert (copied, skipped) == (0, 1)
    assert store._registration(reg.id).team_id == team.id


def test_delete_rechecks_database_after_preview(tmp_path):
    store, league, team, player = setup(tmp_path)
    assert store.deletion_blockers("player", player.id) == []
    concurrent = RegistrationStore(store.path)
    concurrent.register_bowler(league.id, player.name, team_id=team.id)
    with pytest.raises(RegistrationDataError, match="registrations"):
        store.delete_player(player.id)
    assert len(RegistrationStore(store.path).bowlers) == 1


def test_new_vacancy_history_does_not_block_unused_player(tmp_path):
    store, league, team, player = setup(tmp_path)
    scores = ScoringStore(store)
    week = scores.create_session(league.id, 1)
    scores.add_vacancy(week.id, team.id)
    line = scores.score_sheet(week.id)[0].line
    scores.remove_line(line.id, "Vacancy no longer needed")
    assert store.deletion_blockers("player", player.id) == []
    store.delete_player(player.id)


def test_schema_five_upgrade_and_legacy_unknown_history(tmp_path):
    store, league, team, player = setup(tmp_path)
    store.register_bowler(league.id, player.name, team_id=team.id)
    scores = ScoringStore(store)
    week = scores.create_session(league.id, 1)
    line = scores.score_sheet(week.id)[0].line
    scores.save_line_scores(line.id, 150, [(GameStatus.BOWLED, 150)]*3)
    scores.remove_line(line.id, "Old correction")
    with sqlite3.connect(store.path) as db:
        db.executescript("ALTER TABLE bowlers DROP COLUMN archived; "
                         "ALTER TABLE teams DROP COLUMN archived; "
                         "ALTER TABLE score_change_log DROP COLUMN bowler_id; "
                         "PRAGMA user_version = 5;")
    restarted = RegistrationStore(store.path)
    assert restarted.path.with_name("test.schema-v5-backup.db").exists()
    assert not restarted._bowler(player.id).archived
    assert any("legacy" in b for b in restarted.deletion_blockers("player", player.id))


def test_200_bowler_local_workflow_preserves_counts(tmp_path):
    store = RegistrationStore(tmp_path / "workload.db")
    league = store.add_competition("Large league", "2026", CompetitionKind.LEAGUE)
    for team in range(20):
        store.register_team(league.id, f"Team {team:02}", [
            InputBowler(name=f"Player {team:02} {player:02}") for player in range(10)
        ])
    rounds = ScheduleStore(store).generate_round_robin(league.id)
    scores = ScoringStore(store)
    week = scores.create_session(league.id, 1)
    standings = StandingsStore(store)
    standings.link(rounds[0].id, week.id)
    assert len(scores.score_sheet(week.id)) == 200
    assert len(rounds) == 19
    assert len(standings.standings(league.id)) == 20
    assert all(t.played == 0 for t in standings.standings(league.id))
    restarted = RegistrationStore(store.path)
    assert len(restarted.bowlers) == 200
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
