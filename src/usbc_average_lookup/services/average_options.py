from __future__ import annotations

from collections.abc import Iterable

from usbc_average_lookup.models import (
    AverageCondition,
    AverageOption,
    AverageSource,
    CompositeAverage,
)


def composite_options(records: Iterable[CompositeAverage]) -> list[AverageOption]:
    options: list[AverageOption] = []
    for index, record in enumerate(records):
        condition = (
            AverageCondition.SPORT
            if record.sport
            else AverageCondition.CHALLENGE
            if record.challenge
            else AverageCondition.STANDARD
        )
        options.append(
            AverageOption(
                key=f"composite:{record.year}:{condition.value}:{index}",
                average=record.average,
                games=record.games,
                season=record.year,
                source=AverageSource.COMPOSITE,
                condition=condition,
                hand=record.hand,
            )
        )
    return options


def filter_average_options(
    options: Iterable[AverageOption],
    *,
    minimum_games: int = 21,
    season: str = "",
    condition: str = "",
    league: str = "",
    center: str = "",
    include_rerates: bool = True,
    qualifying_only: bool = True,
    sort_by: str = "Newest",
) -> list[AverageOption]:
    """Filter choices without modifying or discarding the stored source data."""

    season_key = season.casefold().strip()
    condition_key = condition.casefold().strip()
    league_key = league.casefold().strip()
    center_key = center.casefold().strip()
    filtered: list[AverageOption] = []
    for option in options:
        if not include_rerates and option.source is AverageSource.RERATE:
            continue
        if season_key and option.season.casefold() != season_key:
            continue
        if condition_key and option.condition.value.casefold() != condition_key:
            continue
        if league_key and league_key not in option.league.casefold():
            continue
        location = " ".join((option.center, option.association)).casefold()
        if center_key and center_key not in location:
            continue
        if (
            qualifying_only
            and option.source is not AverageSource.RERATE
            and (option.games is None or option.games < minimum_games)
        ):
            continue
        filtered.append(option)

    if sort_by == "Highest average":
        return sorted(filtered, key=lambda item: item.average, reverse=True)
    if sort_by == "Most games":
        return sorted(filtered, key=lambda item: item.games or -1, reverse=True)
    return sorted(filtered, key=lambda item: _season_key(item.season), reverse=True)


def suggested_option(options: Iterable[AverageOption]) -> AverageOption | None:
    """Preselect the newest standard composite, but never confirm it."""

    standard = [
        option
        for option in options
        if option.source is AverageSource.COMPOSITE
        and option.condition is AverageCondition.STANDARD
        and (option.games or 0) > 0
    ]
    return max(standard, key=lambda item: _season_key(item.season), default=None)


def _season_key(value: str) -> tuple[int, str]:
    digits = "".join(character for character in value if character.isdigit())
    try:
        return int(digits[-4:]), value
    except ValueError:
        return -1, value
