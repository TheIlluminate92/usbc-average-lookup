import io

import pytest

from usbc_average_lookup.services import bowl_api
from usbc_average_lookup.services.bowl_api import (
    BowlApiError,
    HttpBowlApi,
    _parse_composite_average,
    _parse_league_average,
    _parse_member,
    _parse_rerated_average,
    _split_membership_id,
    _split_name,
)


def test_splits_membership_id() -> None:
    assert _split_membership_id("1234-567890") == ("1234", "567890")


def test_rejects_invalid_membership_id() -> None:
    with pytest.raises(ValueError, match="must look like"):
        _split_membership_id("1234567890")


def test_splits_first_and_last_name() -> None:
    assert _split_name("Alex Q Bowler") == ("Alex", "Bowler")


def test_parses_member_response() -> None:
    member = _parse_member(
        {
            "id": "100",
            "prefix": "1234",
            "suffix": "567890",
            "first": "Alex",
            "last": "Bowler",
            "active": True,
            "assn": "Example USBC",
            "assnstate": "TX",
        }
    )

    assert member.display_name == "Alex Bowler"
    assert member.active is True


def test_parses_composite_average_response() -> None:
    average = _parse_composite_average(
        {
            "year": "2025",
            "sport": False,
            "challenge": False,
            "games": 188,
            "avg": 153,
        }
    )

    assert average.year == "2025"
    assert average.average == 153
    assert average.games == 188


def test_parses_league_and_converted_average_choices() -> None:
    options = _parse_league_average(
        {
            "year": "2025",
            "leagueName": "Tuesday Twisters",
            "avg": 156,
            "games": 72,
            "convAvg": 168,
            "condition": "Sport",
            "centerName": "Lucky Strike",
        }
    )

    assert [option.average for option in options] == [156, 168]
    assert options[0].league == "Tuesday Twisters"
    assert options[0].condition.value == "Sport"
    assert options[1].original_average == 156


def test_parses_rerated_average_choice() -> None:
    option = _parse_rerated_average(
        {
            "dateAdjusted": "2025-04-13",
            "adjustedAverage": 197,
            "enteringAverage": 162,
            "tournamentAdjustedIn": "State Tournament",
            "adjustedBy": "Tournament Director",
        }
    )

    assert option.average == 197
    assert option.original_average == 162
    assert option.tournament == "State Tournament"


def test_unsuccessful_empty_member_search_is_not_found(monkeypatch) -> None:
    response = io.BytesIO(
        b'{"isSuccess": false, "validationErrors": [], "errors": [], "data": null}'
    )
    monkeypatch.setattr(bowl_api, "urlopen", lambda request, timeout: response)

    assert HttpBowlApi(lambda: "token").search_members("Missing Bowler") == []


def test_member_search_preserves_service_validation_message(monkeypatch) -> None:
    response = io.BytesIO(
        b'{"isSuccess": false, "validationErrors": ["Narrow the search"], "errors": []}'
    )
    monkeypatch.setattr(bowl_api, "urlopen", lambda request, timeout: response)

    with pytest.raises(BowlApiError, match="Narrow the search"):
        HttpBowlApi(lambda: "token").search_members("Common Bowler")


def test_member_search_uses_candidates_even_when_service_reports_an_error(
    monkeypatch,
) -> None:
    response = io.BytesIO(
        b'''{
            "isSuccess": false,
            "validationErrors": [],
            "errors": ["Unexpected error occured, please contact the administrator."],
            "data": {
                "results": [
                    {
                        "id": "100",
                        "prefix": "1234",
                        "suffix": "567890",
                        "first": "Alex",
                        "last": "Bowler",
                        "active": true,
                        "assn": "Example USBC",
                        "assnstate": "TX"
                    },
                    {
                        "id": "101",
                        "prefix": "1234",
                        "suffix": "999999",
                        "first": "Alex",
                        "last": "Bowler",
                        "active": true,
                        "assn": "Another USBC",
                        "assnstate": "OK"
                    }
                ]
            }
        }'''
    )
    monkeypatch.setattr(bowl_api, "urlopen", lambda request, timeout: response)

    members = HttpBowlApi(lambda: "token").search_members("Alex Bowler")

    assert len(members) == 2
    assert [member.suffix for member in members] == ["567890", "999999"]


@pytest.mark.parametrize(
    ("name", "membership_id", "expected_path"),
    [
        ("David Brown", "", "/Mobile/api/v1/members/?"),
        ("", "7823-337415", "/Mobile/api/v1/members/id?"),
    ],
)
def test_member_search_uses_the_correct_route(
    monkeypatch, name: str, membership_id: str, expected_path: str
) -> None:
    requested_urls: list[str] = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return io.BytesIO(
            b'{"isSuccess": true, "validationErrors": [], "errors": [], '
            b'"data": {"results": []}}'
        )

    monkeypatch.setattr(bowl_api, "urlopen", fake_urlopen)

    HttpBowlApi(lambda: "token").search_members(name, membership_id)

    assert expected_path in requested_urls[0]


def test_collects_composite_league_converted_and_rerated_choices(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        if "compositeaverages" in request.full_url:
            body = b'''{
                "isSuccess": true,
                "data": {"results": [
                    {"year": "2025", "sport": false, "challenge": false,
                     "games": 100, "avg": 180}
                ]}
            }'''
        elif "leagueactivities" in request.full_url:
            body = b'''{
                "isSuccess": true,
                "data": {"results": [
                    {"year": "2025", "league": "Test League", "games": 60,
                     "avg": 175, "convAvg": 182, "sport": true}
                ]}
            }'''
        else:
            body = b'''{
                "isSuccess": true,
                "data": {"results": [
                    {"adjustedAverage": 190, "enteringAverage": 180,
                     "tournament": "Test Event", "dateAdjusted": "2025-01-01"}
                ]}
            }'''
        return io.BytesIO(body)

    monkeypatch.setattr(bowl_api, "urlopen", fake_urlopen)

    options = HttpBowlApi(lambda: "token").get_average_options("1234", "567890")

    assert [option.average for option in options] == [180, 175, 182, 190]
    assert any("leagueactivities" in url for url in requested_urls)
    assert any("reratedaverage" in url for url in requested_urls)
