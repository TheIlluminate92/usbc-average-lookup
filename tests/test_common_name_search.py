"""Regression coverage for large searches and persistent export controls."""

import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

from usbc_average_lookup.models import InputBowler, Member
from usbc_average_lookup.services import bowl_api
from usbc_average_lookup.services.bowl_api import HttpBowlApi, IncompleteMemberSearchError
from usbc_average_lookup.services.refresh import refresh_bowlers, stored_candidates


def page(number, total=3):
    return {
        "isSuccess": True,
        "data": {
            "totalPages": total,
            "results": [
                {
                    "id": str(number),
                    "prefix": "1234",
                    "suffix": str(number),
                    "first": "John",
                    "last": "Smith",
                    "active": True,
                    "assnstate": "TX",
                }
            ],
        },
    }


def test_large_search_follows_small_pages_with_location_filters(monkeypatch):
    calls = []

    def request(req, timeout):
        query = parse_qs(urlparse(req.full_url).query)
        calls.append(query)
        return io.BytesIO(json.dumps(page(int(query["Page"][0]))).encode())

    monkeypatch.setattr(bowl_api, "urlopen", request)
    members = HttpBowlApi(lambda: "session").search_members(
        "John Smith", state="TX", zip_code="78401"
    )
    assert [member.suffix for member in members] == ["1", "2", "3"]
    assert all(
        q["Size"] == ["10"] and q["State"] == ["TX"] and q["Zip"] == ["78401"] for q in calls
    )


def test_timeout_after_first_page_keeps_candidates_without_choosing_identity(monkeypatch, tmp_path):
    from usbc_average_lookup.database import BowlerDatabase

    def request(req, timeout):
        if parse_qs(urlparse(req.full_url).query)["Page"] == ["2"]:
            raise TimeoutError()
        return io.BytesIO(json.dumps(page(1)).encode())

    monkeypatch.setattr(bowl_api, "urlopen", request)
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("John Smith")]).added[0]
    result = refresh_bowlers(db, lambda: HttpBowlApi(lambda: "session"), [bowler_id])[0]
    assert result.status == "Choose member"
    row = db.get(bowler_id)
    assert row["membership_id"] is None
    assert "incomplete" in row["note"] and "too long" in row["note"]
    assert stored_candidates(row)[0].suffix == "1"
    assert not db.averages(bowler_id)


def test_first_page_timeout_gives_actionable_search_hint(monkeypatch):
    def request(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(bowl_api, "urlopen", request)
    with pytest.raises(bowl_api.BowlApiError, match="narrow by state or ZIP"):
        HttpBowlApi(lambda: "session").search_members("John Smith")


def test_search_filters_are_used_only_for_unresolved_names(tmp_path):
    from usbc_average_lookup.database import BowlerDatabase

    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("John Smith")]).added[0]
    db.set_identity(bowler_id, "John Smith", "", search_state="TX", search_zip="78401")
    calls = []

    class Api:
        def search_members(self, **kwargs):
            calls.append(kwargs)
            return [Member("1", "1234", "1", "John", "Smith", True)]

        def get_composite_averages(self, *args):
            return []

    refresh_bowlers(db, Api, [bowler_id])
    refresh_bowlers(db, Api, [bowler_id])
    assert calls == [
        {"name": "John Smith", "membership_id": "", "state": "TX", "zip_code": "78401"},
        {"name": "", "membership_id": "1234-1"},
    ]


def test_repeated_page_stops_without_silently_choosing_member(monkeypatch):
    monkeypatch.setattr(
        bowl_api, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(page(1)).encode())
    )
    with pytest.raises(IncompleteMemberSearchError, match="repeated a page") as caught:
        HttpBowlApi(lambda: "session").search_members("John Smith")
    assert len(caught.value.members) == 1
