import io
import json
from dataclasses import replace
from pathlib import Path
from threading import Event
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.models import InputBowler, Member
from usbc_average_lookup.services import bowl_api
from usbc_average_lookup.services.bowl_api import BowlApiError, HttpBowlApi


def test_averages_follow_all_pages_and_keep_sanitized_payloads(monkeypatch):
    requested = []

    def request(req, timeout):
        page = int(parse_qs(urlparse(req.full_url).query)["page"][0])
        requested.append(page)
        return io.BytesIO(
            json.dumps(
                {
                    "isSuccess": True,
                    "token": "secret",
                    "data": {
                        "totalPages": 2,
                        "results": [
                            {
                                "year": str(2027 - page),
                                "games": 60,
                                "avg": 190,
                                "sport": False,
                                "challenge": False,
                                "hand": "L",
                                "extra": {"useful": 1, "cookie": "secret"},
                            }
                        ],
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(bowl_api, "urlopen", request)
    api = HttpBowlApi(lambda: "session")
    averages = api.get_composite_averages("1234", "567")
    assert requested == [1, 2]
    assert [a.year for a in averages] == ["2026", "2025"]
    assert averages[0].hand == "L"
    assert averages[0].raw["extra"] == {"useful": 1}
    assert "secret" not in json.dumps(api.snapshots)


def test_incomplete_page_does_not_look_like_success(monkeypatch):
    monkeypatch.setattr(
        bowl_api,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(
            b'{"isSuccess":true,"data":{"totalPages":2,"results":[]}}'
        ),
    )
    with pytest.raises(BowlApiError, match="incomplete page"):
        HttpBowlApi(lambda: "session").get_composite_averages("1234", "1")


def test_member_normalization_retains_all_flags_and_extra_fields():
    member = bowl_api._parse_member(
        {
            "id": "1",
            "prefix": "1234",
            "suffix": "5",
            "first": "Alex",
            "init": "Q",
            "last": "Bowler",
            "active": True,
            "gender": "M",
            "from": "2026-08-01",
            "thru": "2027-07-31",
            "prod": "Natl Assoc",
            "stringpin": True,
            "jrgoldfuture": False,
            "extra": "keep",
        }
    )
    assert member.middle_initial == "Q"
    assert member.membership_thru == "2027-07-31"
    assert member.flags["jrgoldfuture"] is False
    assert member.raw["extra"] == "keep"


def test_league_activity_fixture_normalization_and_history(monkeypatch, tmp_path):
    payload = Path(__file__).with_name("fixtures").joinpath("league_activities.json").read_bytes()
    monkeypatch.setattr(bowl_api, "urlopen", lambda *a, **k: io.BytesIO(payload))
    api = HttpBowlApi(lambda: "session")
    rows = api.get_league_averages("1234", "1")
    assert rows[0].league_name == "Example Monday League"
    assert rows[1].string_pin is True
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Alex Bowler", "1234-1")]).added[0]
    member = Member("1", "1234", "1", "Alex", "Bowler", True)
    db.save_refresh(bowler_id, member, [], api.snapshots, league_averages=rows)
    db.save_refresh(
        bowler_id, member, [], {}, league_averages=[replace(rows[0], average=150, games=90)]
    )
    assert len(db.league_averages(bowler_id)) == 2
    assert len(db.league_averages(bowler_id, history=True)) == 3
    from usbc_average_lookup.services.database_exports import AverageRule, export_preview

    selected = export_preview(db, [bowler_id], AverageRule(source="League", mode="Highest"))
    assert selected[0]["average"]["average"] == 160


@pytest.mark.parametrize(
    "data", [None, {}, {"results": [], "totalPages": -1}, {"results": [], "totalPages": True}]
)
def test_malformed_success_cannot_erase_or_replace_data(monkeypatch, data):
    monkeypatch.setattr(
        bowl_api,
        "urlopen",
        lambda *a, **k: io.BytesIO(json.dumps({"isSuccess": True, "data": data}).encode()),
    )
    with pytest.raises(BowlApiError):
        HttpBowlApi(lambda: "session").get_composite_averages("1234", "1")


def test_cancel_stops_before_next_http_request(monkeypatch):
    cancel = Event()
    cancel.set()
    monkeypatch.setattr(bowl_api, "urlopen", lambda *a, **k: pytest.fail("Request after cancel"))
    with pytest.raises(bowl_api.ApiCancelledError):
        HttpBowlApi(lambda: "session", cancel=cancel).get_composite_averages("1234", "1")


def test_rate_limit_is_explicit(monkeypatch):
    def request(*args, **kwargs):
        raise HTTPError("https://example.invalid", 429, "Too many requests", {}, None)

    monkeypatch.setattr(bowl_api, "urlopen", request)
    with pytest.raises(bowl_api.RateLimitedError):
        HttpBowlApi(lambda: "session").get_composite_averages("1234", "1")
