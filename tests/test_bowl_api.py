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
