from usbc_average_lookup.models import AverageCondition, AverageOption, AverageSource
from usbc_average_lookup.services.average_options import filter_average_options


def option(
    key: str,
    average: int,
    *,
    games: int | None,
    season: str = "2025",
    condition: AverageCondition = AverageCondition.STANDARD,
    source: AverageSource = AverageSource.LEAGUE,
    league: str = "Tuesday Twisters",
) -> AverageOption:
    return AverageOption(
        key=key,
        average=average,
        games=games,
        season=season,
        condition=condition,
        source=source,
        league=league,
    )


def test_minimum_games_is_configurable_and_does_not_remove_source_data() -> None:
    records = [option("short", 200, games=12), option("qualified", 180, games=21)]

    assert [item.key for item in filter_average_options(records, minimum_games=21)] == [
        "qualified"
    ]
    assert len(records) == 2
    assert len(filter_average_options(records, minimum_games=12)) == 2


def test_filters_by_season_type_and_league() -> None:
    records = [
        option("standard", 180, games=30),
        option(
            "sport",
            170,
            games=40,
            season="2024",
            condition=AverageCondition.SPORT,
            league="Monday Sport",
        ),
    ]

    filtered = filter_average_options(
        records,
        season="2024",
        condition="Sport",
        league="Monday",
    )

    assert [item.key for item in filtered] == ["sport"]


def test_rerates_remain_visible_without_a_game_count() -> None:
    rerate = option(
        "rerate",
        195,
        games=None,
        condition=AverageCondition.ADJUSTED,
        source=AverageSource.RERATE,
        league="",
    )

    assert filter_average_options([rerate], minimum_games=21) == [rerate]
    assert filter_average_options([rerate], include_rerates=False) == []
