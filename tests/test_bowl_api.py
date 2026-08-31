import io

import pytest

from usbc_average_lookup.services import bowl_api
from usbc_average_lookup.services.bowl_api import (
    BowlApiError,
    HttpBowlApi,
    _parse_composite_average,
    _parse_member,
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
