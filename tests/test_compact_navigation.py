from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from usbc_average_lookup.registration_ui import RegistrationDesk
from usbc_average_lookup.services.registration import CompetitionKind
from usbc_average_lookup.ui_helpers import ButtonHint


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("League home", "Home"),
        ("Teams & roster", "Teams"),
        ("Schedule & lanes", "Schedule"),
        ("Scores & history", "Scores"),
        ("Rules & setup", "Rules"),
        ("Player directory", "Players"),
        ("All leagues", "All leagues"),
    ],
)
def test_short_and_legacy_names_open_the_same_section(old, new) -> None:
    desk = RegistrationDesk.__new__(RegistrationDesk)
    notebook = Mock()
    notebook.tabs.return_value = ("home", "target")
    notebook.tab.side_effect = lambda tab_id, _option: (
        new if tab_id == "target" else "unrelated"
    )
    desk.section_tabs = notebook

    desk.select_section(old)
    notebook.select.assert_called_with("target")
    notebook.select.reset_mock()
    desk.select_section(new)
    notebook.select.assert_called_once_with("target")


@pytest.mark.parametrize(
    ("kind", "withdrawn", "label"),
    [
        (CompetitionKind.LEAGUE, False, "Withdraw from league"),
        (CompetitionKind.TOURNAMENT, False, "Withdraw from tournament"),
        (CompetitionKind.LEAGUE, True, "Restore registration"),
    ],
)
def test_withdrawal_label_keeps_the_action_explicit(kind, withdrawn, label) -> None:
    desk = RegistrationDesk.__new__(RegistrationDesk)
    desk._selected_view = lambda: SimpleNamespace(
        registration=SimpleNamespace(withdrawn=withdrawn)
    )
    desk._current_competition = lambda: SimpleNamespace(kind=kind)
    desk.api_provider = lambda: None
    desk.edit_button = Mock()
    desk.withdraw_button = Mock()
    desk.review_button = Mock()

    desk._update_row_actions()

    desk.withdraw_button.configure.assert_any_call(text=label)


def test_hints_preserve_existing_bindings_and_cancel_on_exit() -> None:
    widget = Mock()
    widget.after.return_value = "hint-timer"
    hint = ButtonHint(widget, "Explanation")
    for event in ("<Enter>", "<FocusIn>", "<Leave>", "<FocusOut>", "<Destroy>", "<Escape>"):
        assert any(
            call.args[0] == event and call.kwargs == {"add": "+"}
            for call in widget.bind.call_args_list
        )

    hint._schedule()
    assert hint.pending == "hint-timer"
    popup = Mock()
    hint.window = popup
    hint._hide()
    widget.after_cancel.assert_called_once_with("hint-timer")
    popup.destroy.assert_called_once()
    assert hint.pending is None
    assert hint.window is None
    hint._hide()
    popup.destroy.assert_called_once()


def test_hint_does_not_open_after_control_is_destroyed() -> None:
    widget = Mock()
    widget.winfo_exists.return_value = False
    hint = ButtonHint(widget, "Explanation")

    hint._show()

    assert hint.window is None
