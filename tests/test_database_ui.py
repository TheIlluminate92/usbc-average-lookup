"""Desktop integration checks run with the real Tk widgets on Windows CI."""

import gc
import os
import tkinter as tk
from threading import Event
from time import monotonic, sleep

import pytest

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.database_app import AverageLookupApp
from usbc_average_lookup.models import CompositeAverage, InputBowler, Member
from usbc_average_lookup.services.auth import AuthSession, AuthState, SignInCancelledError
from usbc_average_lookup.ui import DetailDialog, ExportDialog


@pytest.fixture
def app(tmp_path):
    # Dispose previous Tk interpreter cycles before initializing another one.
    # Collecting an old interpreter during Tcl's init.tcl load can close the
    # new interpreter's file channel on Windows.
    gc.collect()
    db = BowlerDatabase(tmp_path / "ui.sqlite3")
    try:
        window = AverageLookupApp(db)
    except tk.TclError as error:
        if os.environ.get("GITHUB_ACTIONS"):
            raise
        pytest.skip(f"Desktop Tk unavailable: {error}")
    window.withdraw()
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)
    yield window
    try:
        for callback in window.tk.call("after", "info"):
            window.after_cancel(callback)
        window.destroy()
    except tk.TclError:
        pass
    assert not errors


def populate(app):
    bowler_id = app.database.import_bowlers([InputBowler("Alex Bowler", "1234-1")]).added[0]
    app.database.save_refresh(
        bowler_id,
        Member("1", "1234", "1", "Alex", "Bowler", True),
        [CompositeAverage("2025", 60, 180, False, False)],
        {},
    )
    app.render()
    app.update()
    return bowler_id


def pump_until(app, predicate):
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        app.update()
        sleep(0.01)
    assert predicate()


def test_database_search_selection_and_detail_dialog(app):
    bowler_id = populate(app)
    assert app.view.get_children() == (str(bowler_id),)
    app.query.set("nobody")
    assert app.view.get_children() == ()
    app.query.set("alex")
    app.view.selection_set(str(bowler_id))
    app.update()
    assert "disabled" not in app.details_button.state()
    detail = DetailDialog(app, app.database, bowler_id)
    detail.update()
    detail.destroy()


def test_export_preview_changes_when_rule_or_scope_changes(app):
    bowler_id = populate(app)
    dialog = ExportDialog(app, app.database, {"All": [bowler_id]})
    dialog.update()
    assert dialog.preview[0]["average"]["average"] == 180
    dialog.minimum.set("999")
    assert dialog.preview[0]["average"] is None
    assert "disabled" in dialog.save_button.state()
    dialog.variables["missing"].set("Blank")
    assert "disabled" not in dialog.save_button.state()
    dialog.variables["mode"].set("Manual")
    dialog.manual[bowler_id] = app.database.averages(bowler_id)[0]["id"]
    dialog.update_preview()
    assert dialog.preview[0]["average"]["average"] == 180
    dialog.destroy()


def test_cancelled_sign_in_is_quiet_and_late_token_is_ignored(app):
    started = Event()

    class Authenticator:
        def sign_in(self, cancel):
            started.set()
            cancel.wait(2)
            raise SignInCancelledError()

        def sign_out(self):
            pass

    app.authenticator = Authenticator()
    app.toggle_sign_in()
    assert started.wait(1)
    old_generation = app.auth_generation
    app.toggle_sign_in()
    pump_until(app, lambda: not app.signing_in)
    app.events.put(("auth", old_generation, AuthSession(AuthState.SIGNED_IN, bearer_token="test")))
    app.poll_events()
    assert app.auth_session.state == AuthState.SIGNED_OUT
    assert "cancelled" in app.status.cget("text").lower()


def test_progressive_refresh_updates_widgets_on_main_thread(app, monkeypatch):
    from usbc_average_lookup import database_app

    bowler_id = populate(app)

    class Api:
        def __init__(self, token_provider, **kwargs):
            pass

        def search_members(self, **kwargs):
            return [Member("1", "1234", "1", "Alex", "Bowler", True)]

        def get_composite_averages(self, *args):
            return [CompositeAverage("2026", 72, 190, False, False)]

    monkeypatch.setattr(database_app, "HttpBowlApi", Api)
    app.auth_session = AuthSession(AuthState.SIGNED_IN, bearer_token="test")
    app.start_refresh("All")
    pump_until(app, lambda: not app.busy)
    assert app.database.averages(bowler_id)[0]["year"] == "2026"
    assert app.progress["value"] == 1
    assert "complete" in app.status.cget("text").lower()


def test_delete_cancel_confirm_and_busy_guard(app, monkeypatch):
    from usbc_average_lookup import ui

    bowler_id = populate(app)
    duplicate = app.database.import_bowlers(
        [InputBowler("Alex Bowler")], allow_same_name=True
    ).added[0]
    app.render()
    app.view.selection_set(str(duplicate))
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: False)
    app.delete_selected()
    assert len(app.database.list_bowlers()) == 2
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: True)
    app.busy = True
    app.delete_selected()
    assert app.database.get(duplicate)
    app.busy = False
    app.delete_selected()
    assert app.view.get_children() == (str(bowler_id),)
    assert app.database.averages(bowler_id)


@pytest.mark.parametrize("scaling", [1.33, 2.0])
def test_export_save_is_visible_at_small_size_and_writes_file(app, monkeypatch, tmp_path, scaling):
    import csv

    from usbc_average_lookup import ui

    app.tk.call("tk", "scaling", scaling)
    # A transient dialog is hidden while its parent is withdrawn. Show the test
    # window so these assertions measure real, mapped widgets on Windows.
    app.deiconify()
    app.update()
    bowler_id = populate(app)
    missing = app.database.import_bowlers([InputBowler("John Smith")]).added[0]
    dialog = ExportDialog(app, app.database, {"All": [bowler_id, missing]})
    dialog.geometry("940x560")
    dialog.update()
    button = dialog.save_button
    assert button.winfo_ismapped()
    assert button.winfo_rooty() >= dialog.winfo_rooty()
    assert (
        button.winfo_rooty() + button.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
    )
    assert "disabled" in button.state()
    assert "Blank or Skip" in dialog.export_help.cget("text")
    dialog.variables["missing"].set("Skip")
    assert "disabled" not in button.state()
    filename = tmp_path / "BTM.csv"
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kwargs: str(filename))
    button.invoke()
    with filename.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["USBC ID Number"] == "1234-1"
    assert dialog.choice[0] == 1


def test_resolve_filter_keeps_candidate_index_and_search_options(app):
    bowler_id = app.database.import_bowlers([InputBowler("John Smith")]).added[0]
    candidates = [
        Member(
            "1",
            "1234",
            "1",
            "John",
            "Smith",
            False,
            association="Other USBC",
            association_state="OH",
        ),
        Member(
            "2",
            "1234",
            "2",
            "John",
            "Smith",
            True,
            association="Corpus Christi USBC",
            association_state="TX",
        ),
    ]
    app.database.save_status(bowler_id, "Choose member", "Choose", candidates)
    dialog = DetailDialog(app, app.database, bowler_id)
    dialog.match_query.set("corpus tx")
    dialog.match_active.set("Active")
    assert dialog.match_table.get_children() == ("1",)
    dialog.match_table.selection_set("1")
    dialog.pick_member()
    assert dialog.usbc.get() == "1234-2"
    dialog.search_state.set("TX")
    dialog.search_again()
    saved = app.database.get(bowler_id)
    assert saved["search_state"] == "TX"
    assert saved["membership_id"] is None
