from usbc_average_lookup.models import (
    AverageCondition,
    AverageOption,
    AverageSource,
    LookupResult,
    LookupStatus,
)
from usbc_average_lookup.services.average_options import (
    bulk_review_candidates,
    filter_average_options,
)


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
        league="Monday Sport",
    )

    assert [item.key for item in filtered] == ["sport"]

    labeled = filter_average_options(records, league="Monday Sport — 2024")
    assert [item.key for item in labeled] == ["sport"]


def test_league_filter_does_not_include_names_that_only_contain_the_selection() -> None:
    records = [
        option("winter", 166, games=87, league="Monday Misfits"),
        option("summer", 171, games=24, league="Summer Monday Misfits"),
    ]

    filtered = filter_average_options(records, league="Monday Misfits — 2025")

    assert [item.key for item in filtered] == ["winter"]


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


def test_bulk_review_only_prepares_unreviewed_bowlers_and_never_confirms() -> None:
    clean = option("clean", 180, games=30)
    ambiguous = option("ambiguous", 181, games=40)
    results = [
        LookupResult(
            "Clean Bowler",
            LookupStatus.REVIEW_REQUIRED,
            average=180,
            available_averages=(clean,),
            selected_average_key=clean.key,
        ),
        LookupResult(
            "Ambiguous Bowler",
            LookupStatus.REVIEW_REQUIRED,
            average=180,
            available_averages=(clean, ambiguous),
            selected_average_key=clean.key,
        ),
        LookupResult("Already Reviewed", LookupStatus.FOUND, average=190),
    ]

    candidates, excluded = bulk_review_candidates(results)

    assert excluded == 0
    assert [candidate.result_index for candidate in candidates] == [0, 1]
    assert candidates[0].is_clean is True
    assert candidates[1].is_clean is False
    assert results[0].status is LookupStatus.REVIEW_REQUIRED


def test_bulk_review_leaves_filter_mismatches_for_individual_review() -> None:
    short = option("short", 200, games=12)
    result = LookupResult(
        "Short Bowler",
        LookupStatus.REVIEW_REQUIRED,
        average=200,
        available_averages=(short,),
        selected_average_key=short.key,
    )

    candidates, excluded = bulk_review_candidates([result], minimum_games=21)

    assert candidates == []
    assert excluded == 1


def test_bulk_review_handles_150_bowlers_without_skips_or_duplicates() -> None:
    results = []
    for index in range(150):
        choice = option(f"choice-{index}", 150 + index % 50, games=21 + index % 30)
        results.append(
            LookupResult(
                f"Bowler {index + 1}",
                LookupStatus.REVIEW_REQUIRED,
                average=choice.average,
                available_averages=(choice,),
                selected_average_key=choice.key,
            )
        )

    candidates, excluded = bulk_review_candidates(results)

    assert excluded == 0
    assert len(candidates) == 150
    assert [candidate.result_index for candidate in candidates] == list(range(150))
    assert len({candidate.option.key for candidate in candidates}) == 150
    assert all(candidate.is_clean for candidate in candidates)
