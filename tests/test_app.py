from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from usbc_average_lookup.app import AverageLookupApp
from usbc_average_lookup.models import LookupResult, LookupStatus


def result(name: str) -> LookupResult:
    return LookupResult(
        input_name=name,
        status=LookupStatus.FOUND,
        average=180,
    )


def test_late_roster_lookup_cannot_replace_newer_results() -> None:
    app = AverageLookupApp.__new__(AverageLookupApp)
    app.lookup_generation = 2
    app.results = [result("New roster")]

    app._lookup_finished(1, [result("Old roster")])

    assert [item.input_name for item in app.results] == ["New roster"]


def test_late_issue_fix_cannot_write_into_replaced_roster() -> None:
    app = AverageLookupApp.__new__(AverageLookupApp)
    app.lookup_generation = 4
    app.bowlers = []
    app.results = []

    app._fix_finished(3, 10, None, result("Old roster"), False)

    assert app.bowlers == []
    assert app.results == []


def test_dynamic_tab_close_hit_area_tracks_the_tab_right_edge() -> None:
    class Notebook:
        @staticmethod
        def index(position: str) -> int:
            x = int(position.removeprefix("@").split(",", 1)[0])
            return 2 if x < 100 else 3

    app = AverageLookupApp.__new__(AverageLookupApp)
    app.workspace = Notebook()

    assert app._near_tab_right_edge(2, 75, 10)
    assert not app._near_tab_right_edge(2, 50, 10)


def test_popping_out_registration_tab_preserves_league_context() -> None:
    app = AverageLookupApp.__new__(AverageLookupApp)
    page = object()
    desk = SimpleNamespace(
        workspace_context=SimpleNamespace(competition_id="league-2")
    )
    app.workspace_tab_desks = {page: desk}
    app.workspace_tab_kinds = {page: "registration"}
    app._open_registration_window = Mock()
    app._close_workspace_tab = Mock()

    app._pop_out_workspace_tab(page)

    app._open_registration_window.assert_called_once_with("league-2")
    app._close_workspace_tab.assert_called_once_with(page)


@pytest.mark.parametrize(
    "section", ["Home", "Teams", "Schedule", "Scores", "Rules", "Players", "All leagues"]
)
def test_popping_out_management_tab_preserves_section_and_league(section: str) -> None:
    class Sections:
        @staticmethod
        def select() -> str:
            return "scores"

        @staticmethod
        def tab(_selected: str, _option: str) -> str:
            return section

    app = AverageLookupApp.__new__(AverageLookupApp)
    page = object()
    desk = SimpleNamespace(
        workspace_context=SimpleNamespace(competition_id="league-3"),
        section_tabs=Sections(),
    )
    app.workspace_tab_desks = {page: desk}
    app.workspace_tab_kinds = {page: "management"}
    app._open_management_window = Mock()
    app._close_workspace_tab = Mock()

    app._pop_out_workspace_tab(page)

    app._open_management_window.assert_called_once_with(
        section, "league-3"
    )
    app._close_workspace_tab.assert_called_once_with(page)
