import os
import tkinter as tk

import pytest

from usbc_average_lookup.registration_ui import RegistrationDesk
from usbc_average_lookup.services.registration import (
    BowlerProfile,
    CompetitionKind,
    RegistrationStore,
)
from usbc_average_lookup.services.scheduling import ScheduleStore
from usbc_average_lookup.services.scoring import GameStatus, ScoringStore
from usbc_average_lookup.services.standings import StandingsStore
from usbc_average_lookup.workspace import LeagueWorkspaceContext


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        if os.environ.get("GITHUB_ACTIONS"):
            raise
        pytest.skip(f"Local Tk runtime unavailable: {error}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.parametrize("kind", [CompetitionKind.LEAGUE, CompetitionKind.TOURNAMENT])
def test_real_widgets_open_linked_scores_and_standings(tmp_path, kind, tk_root, monkeypatch):
    root = tk_root
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    desk = None
    try:
        store = RegistrationStore(tmp_path / "smoke.db")
        league = store.add_competition("Test", "2026-27", kind)
        for number in range(2):
            team = store.add_team(league.id, f"Team {number}")
            store.register_bowler(league.id, f"Bowler {number}", team_id=team.id)
        round_ = ScheduleStore(store).generate_round_robin(league.id)[0]
        scoring = ScoringStore(store)
        week = scoring.create_session(league.id, 1)
        StandingsStore(store).link(round_.id, week.id)
        desk = RegistrationDesk(root, store, lambda: None, lambda _text: None,
                                workspace_context=LeagueWorkspaceContext(league.id))
        desk.pack()
        for section in ("Home", "Teams", "Schedule", "Scores", "Standings", "Rules", "Players"):
            desk.select_section(section)
            root.update()
            assert desk.section_tabs.tab(desk.section_tabs.select(), "text") == section
        desk._open_scheduled_scores(week.id)
        assert desk.scoring_desk._session().id == week.id
        for view in scoring.score_sheet(week.id):
            scoring.save_line_scores(view.line.id, 150, [(GameStatus.BOWLED, 150)]*3)
        scoring.finalize_session(week.id)
        desk.refresh()
        root.update()
        assert len(desk.standings_desk.table.get_children()) == 2
        assert desk.schedule_desk.score_button.cget("text") == "Open scores"
        notices = []
        monkeypatch.setattr("usbc_average_lookup.registration_ui.messagebox.showinfo",
                            lambda *args, **kwargs: notices.append(args))
        monkeypatch.setattr("usbc_average_lookup.registration_ui.messagebox.askyesno",
                            lambda *args, **kwargs: True)
        player_id = store.bowlers[0].id
        desk.player_table.selection_set(player_id)
        desk.refresh()
        assert desk.player_table.selection() == (player_id,)
        desk._manage_entity("player", delete=True)
        assert notices and store._bowler(player_id)
        desk._manage_entity("player", delete=False)
        assert not desk.player_table.exists(player_id)
        desk.show_archived_players.set(True)
        desk.refresh()
        desk.player_table.selection_set(player_id)
        desk._manage_entity("player", delete=False)
        assert not store._bowler(player_id).archived
        team_id = store.teams[0].id
        desk.team_management_table.selection_set(team_id)
        desk._manage_entity("team", delete=False)
        assert not desk.team_management_table.exists(team_id)
        desk.show_archived_teams.set(True)
        desk.refresh()
        desk.team_management_table.selection_set(team_id)
        desk._manage_entity("team", delete=False)
        assert not store._team(team_id).archived
        empty = BowlerProfile("unused", "Unused")
        store.bowlers.append(empty)
        store.save()
        desk.refresh()
        desk.player_table.selection_set(empty.id)
        monkeypatch.setattr("usbc_average_lookup.registration_ui.messagebox.askyesno",
                            lambda *args, **kwargs: False)
        desk._manage_entity("player", delete=True)
        assert store._bowler(empty.id)
        monkeypatch.setattr("usbc_average_lookup.registration_ui.messagebox.askyesno",
                            lambda *args, **kwargs: True)
        desk._manage_entity("player", delete=True)
        assert not desk.player_table.exists(empty.id)
        empty_team = store.add_team(league.id, "Unused team")
        desk.refresh()
        desk.team_management_table.selection_set(empty_team.id)
        desk._manage_entity("team", delete=True)
        assert not desk.team_management_table.exists(empty_team.id)
        assert not errors
    finally:
        if desk is not None:
            desk.close()
            desk.destroy()
