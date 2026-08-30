import pytest

from usbc_average_lookup.models import CompositeAverage
from usbc_average_lookup.services.average_selector import select_latest_standard


def average(
    year: str,
    value: int,
    *,
    games: int = 30,
    sport: bool = False,
    challenge: bool = False,
) -> CompositeAverage:
    return CompositeAverage(year, games, value, sport, challenge)


def test_selects_newest_standard_composite() -> None:
    records = [average("2024", 137), average("2025", 153)]

    assert select_latest_standard(records) == records[1]


def test_ignores_sport_challenge_and_zero_game_records() -> None:
    standard = average("2024", 137)
    records = [
        standard,
        average("2026", 180, sport=True),
        average("2027", 190, challenge=True),
        average("2028", 200, games=0),
    ]

    assert select_latest_standard(records) == standard


def test_returns_none_when_no_standard_average_exists() -> None:
    assert select_latest_standard([average("2025", 170, sport=True)]) is None


def test_rejects_unexpected_year_format() -> None:
    with pytest.raises(ValueError, match="Unexpected composite-average year"):
        select_latest_standard([average("2024-25", 170)])

