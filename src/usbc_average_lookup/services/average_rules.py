from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import StrEnum

from usbc_average_lookup.models import CompositeAverage, LeagueAverage


class AverageSource(StrEnum):
    STANDARD_COMPOSITE = "Standard composite"
    LEAGUE_ACTIVITY = "League average"
    IMPORTED = "Imported average"
    MANUAL = "Manual average"


class AverageSelection(StrEnum):
    LATEST = "Newest season"
    HIGHEST = "Highest average"
    MOST_GAMES = "Most games"


class AverageRounding(StrEnum):
    NEAREST = "Nearest whole pin"
    DOWN = "Round down"
    UP = "Round up"


@dataclass(frozen=True, slots=True)
class AverageCandidate:
    source: AverageSource
    average: int
    games: int | None = None
    year: str = ""
    label: str = ""
    league_id: str = ""
    sport: bool = False
    challenge: bool = False
    string_pin: bool = False

    def __post_init__(self) -> None:
        if self.average < 0:
            raise ValueError("Average candidates cannot be negative")
        if self.games is not None and self.games < 0:
            raise ValueError("Game counts cannot be negative")


@dataclass(frozen=True, slots=True)
class RuleSource:
    source: AverageSource
    minimum_games: int = 0
    selection: AverageSelection = AverageSelection.LATEST
    league_ids: tuple[str, ...] = ()
    allow_sport: bool = False
    allow_challenge: bool = False
    allow_string_pin: bool = True

    def __post_init__(self) -> None:
        if self.minimum_games < 0:
            raise ValueError("Minimum games cannot be negative")


@dataclass(frozen=True, slots=True)
class AverageRule:
    name: str
    sources: tuple[RuleSource, ...] = (
        RuleSource(AverageSource.STANDARD_COMPOSITE),
    )
    multiplier: Decimal = Decimal("1")
    add_pins: int = 0
    rounding: AverageRounding = AverageRounding.NEAREST
    minimum_result: int | None = None
    maximum_result: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Average rules require a name")
        if not self.sources:
            raise ValueError("Average rules require at least one source")
        if not self.multiplier.is_finite() or self.multiplier < 0:
            raise ValueError("Average-rule multiplier must be a non-negative number")
        if self.minimum_result is not None and self.minimum_result < 0:
            raise ValueError("Minimum result cannot be negative")
        if self.maximum_result is not None and self.maximum_result < 0:
            raise ValueError("Maximum result cannot be negative")
        if (
            self.minimum_result is not None
            and self.maximum_result is not None
            and self.minimum_result > self.maximum_result
        ):
            raise ValueError("Minimum result cannot exceed maximum result")


@dataclass(frozen=True, slots=True)
class AverageDecision:
    average: int
    candidate: AverageCandidate
    unrounded_average: Decimal
    source_position: int
    explanation: str


def candidates_from_composites(
    records: Iterable[CompositeAverage],
) -> list[AverageCandidate]:
    return [
        AverageCandidate(
            source=AverageSource.STANDARD_COMPOSITE,
            average=record.average,
            games=record.games,
            year=record.year,
            label=f"{record.year} standard composite",
            sport=record.sport,
            challenge=record.challenge,
        )
        for record in records
    ]


def candidates_from_league_averages(
    records: Iterable[LeagueAverage],
) -> list[AverageCandidate]:
    return [
        AverageCandidate(
            source=AverageSource.LEAGUE_ACTIVITY,
            average=record.adjusted_average or record.average,
            games=record.games,
            year=record.year,
            label=f"{record.league_name} ({record.year})",
            league_id=record.league_id,
            sport=record.sport,
            challenge=record.challenge,
            string_pin=record.string_pin,
        )
        for record in records
    ]


def evaluate_average_rule(
    rule: AverageRule,
    candidates: Iterable[AverageCandidate],
) -> AverageDecision | None:
    candidate_list = list(candidates)
    for position, source_rule in enumerate(rule.sources):
        eligible = [
            candidate
            for candidate in candidate_list
            if _matches_source_rule(candidate, source_rule)
        ]
        if not eligible:
            continue
        selected = _select_candidate(eligible, source_rule.selection)
        unrounded = Decimal(selected.average) * rule.multiplier + Decimal(rule.add_pins)
        result = _round_average(unrounded, rule.rounding)
        if rule.minimum_result is not None:
            result = max(result, rule.minimum_result)
        if rule.maximum_result is not None:
            result = min(result, rule.maximum_result)
        return AverageDecision(
            average=result,
            candidate=selected,
            unrounded_average=unrounded,
            source_position=position,
            explanation=_explanation(rule, selected, unrounded, result),
        )
    return None


def _matches_source_rule(candidate: AverageCandidate, rule: RuleSource) -> bool:
    if candidate.source is not rule.source:
        return False
    if candidate.games is None and rule.minimum_games:
        return False
    if candidate.games is not None and candidate.games < rule.minimum_games:
        return False
    if rule.league_ids and candidate.league_id not in rule.league_ids:
        return False
    if candidate.sport and not rule.allow_sport:
        return False
    if candidate.challenge and not rule.allow_challenge:
        return False
    return not candidate.string_pin or rule.allow_string_pin


def _select_candidate(
    candidates: list[AverageCandidate],
    selection: AverageSelection,
) -> AverageCandidate:
    if selection is AverageSelection.HIGHEST:
        return max(candidates, key=lambda item: (item.average, _year_key(item), _games(item)))
    if selection is AverageSelection.MOST_GAMES:
        return max(candidates, key=lambda item: (_games(item), _year_key(item), item.average))
    return max(candidates, key=lambda item: (_year_key(item), _games(item), item.average))


def _year_key(candidate: AverageCandidate) -> int:
    try:
        return int(candidate.year)
    except ValueError:
        return -1


def _games(candidate: AverageCandidate) -> int:
    return candidate.games if candidate.games is not None else -1


def _round_average(value: Decimal, rounding: AverageRounding) -> int:
    if rounding is AverageRounding.DOWN:
        return int(value.to_integral_value(rounding=ROUND_FLOOR))
    if rounding is AverageRounding.UP:
        return int(value.to_integral_value(rounding=ROUND_CEILING))
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _explanation(
    rule: AverageRule,
    candidate: AverageCandidate,
    unrounded: Decimal,
    result: int,
) -> str:
    label = candidate.label or candidate.source.value
    if rule.multiplier == 1 and rule.add_pins == 0:
        calculation = str(candidate.average)
    else:
        calculation = (
            f"{candidate.average} × {rule.multiplier}"
            f" {rule.add_pins:+d} = {unrounded}"
        )
    if Decimal(result) != unrounded:
        calculation += f" → {result}"
    return f"{label}: {calculation} ({rule.name})"
