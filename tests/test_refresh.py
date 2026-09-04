from dataclasses import replace
from threading import Event, Lock
from time import sleep

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.models import CompositeAverage, InputBowler, Member
from usbc_average_lookup.services.bowl_api import AuthenticationExpiredError, BowlApiError
from usbc_average_lookup.services.refresh import refresh_bowlers


class FakeApi:
    def search_members(self, name="", membership_id=""):
        return [Member("1", "1234", membership_id.split("-")[-1] or "1", "Alex", "Bowler", True)]

    def get_composite_averages(self, prefix, suffix):
        return [CompositeAverage("2025", 60, 180, False, False)]


def test_refresh_by_saved_id_and_progressive_persistence(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    ids = db.import_bowlers([InputBowler("Name Bowler", f"1234-{i}") for i in range(8)]).added
    calls, progress, live = [], [], [0, 0]
    lock = Lock()

    class Api(FakeApi):
        def search_members(self, name="", membership_id=""):
            assert name == ""
            calls.append(membership_id)
            with lock:
                live[0] += 1
                live[1] = max(live)
            sleep(0.03)
            with lock:
                live[0] -= 1
            return super().search_members(name, membership_id)

    def on_progress(event):
        assert db.get(event.bowler_id)["status"] == "Refreshed"
        progress.append(event.completed)

    results = refresh_bowlers(db, Api, ids, workers=3, progress=on_progress)
    assert len(results) == 8
    assert sorted(calls) == [f"1234-{i}" for i in range(8)]
    assert 1 < live[1] <= 3
    assert progress == list(range(1, 9))


def test_cancel_stops_scheduling_and_preserves_finished_data(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    ids = db.import_bowlers([InputBowler("Name Bowler", f"1234-{i}") for i in range(6)]).added
    cancel = Event()
    results = refresh_bowlers(
        db, FakeApi, ids, workers=1, cancel=cancel, progress=lambda event: cancel.set()
    )
    assert len(results) == 1
    assert db.get(ids[0])["status"] == "Refreshed"
    assert db.get(ids[1])["status"] == "Not refreshed"


def test_expired_auth_stops_batch_without_clearing_history(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    ids = db.import_bowlers([InputBowler("Name Bowler", f"1234-{i}") for i in range(3)]).added
    refresh_bowlers(db, FakeApi, ids)

    class Api(FakeApi):
        def search_members(self, **kwargs):
            raise AuthenticationExpiredError()

    results = refresh_bowlers(db, Api, ids, workers=1)
    assert len(results) == 1
    assert results[0].status == "Sign in again"
    assert db.averages(ids[0])[0]["average"] == 180


def test_ambiguous_name_is_saved_for_review_without_fetching_averages(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Common Bowler")]).added[0]

    class Api(FakeApi):
        def search_members(self, **kwargs):
            member = super().search_members(membership_id="1234-1")[0]
            return [member, replace(member, suffix="2")]

        def get_composite_averages(self, *args):
            raise AssertionError("Must resolve identity first")

    result = refresh_bowlers(db, Api, [bowler_id])[0]
    assert result.status == "Choose member"
    assert db.get(bowler_id)["membership_id"] is None
    assert "1234" in db.get(bowler_id)["candidates_json"]


def test_api_failure_isolated_and_other_bowlers_finish(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    ids = db.import_bowlers([InputBowler("Name Bowler", f"1234-{i}") for i in range(2)]).added

    class Api(FakeApi):
        def get_composite_averages(self, prefix, suffix):
            if suffix == "0":
                raise BowlApiError("HTTP 429")
            return super().get_composite_averages(prefix, suffix)

    assert {r.status for r in refresh_bowlers(db, Api, ids)} == {"Refresh failed", "Refreshed"}
