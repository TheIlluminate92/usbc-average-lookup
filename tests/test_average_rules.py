from decimal import Decimal

from usbc_average_lookup.models import CompositeAverage, LeagueAverage
from usbc_average_lookup.services.average_rules import (
    AverageCandidate,
    AverageRounding,
    AverageRule,
    AverageSelection,
    AverageSource,
    RuleSource,
    candidates_from_composites,
    candidates_from_league_averages,
    evaluate_average_rule,
)


def league_average(
    league_id: str,
    average: int,
    games: int,
    *,
    year: str = "2025",
    string_pin: bool = False,
    adjusted_average: int = 0,
) -> LeagueAverage:
    return LeagueAverage(
        league_id=league_id,
        league_name=f"League {league_id}",
        season="W",
        center_id="center",
        center_name="Example Center",
        association_id="association",
        association_name="Example Association",
        association_number="00000",
        year=year,
        average=average,
        games=games,
        sport=False,
        challenge=False,
        roll_and_grow=False,
        bumper=False,
        string_pin=string_pin,
        adjusted_average=adjusted_average,
    )


def test_uses_latest_standard_composite_by_default() -> None:
    candidates = candidates_from_composites(
        [
            CompositeAverage("2024", 30, 145, False, False),
            CompositeAverage("2025", 60, 153, False, False),
        ]
    )

    decision = evaluate_average_rule(AverageRule("Standard composite"), candidates)

    assert decision is not None
    assert decision.average == 153
    assert decision.candidate.year == "2025"


def test_applies_multiplier_with_explicit_rounding() -> None:
    rule = AverageRule(
        "Ninety percent composite",
        multiplier=Decimal("0.90"),
        rounding=AverageRounding.DOWN,
    )
    candidate = AverageCandidate(
        AverageSource.STANDARD_COMPOSITE,
        181,
        games=72,
        year="2025",
    )

    decision = evaluate_average_rule(rule, [candidate])

    assert decision is not None
    assert decision.unrounded_average == Decimal("162.90")
    assert decision.average == 162


def test_selects_a_linked_previous_league_average() -> None:
    rule = AverageRule(
        "Previous Monday league",
        sources=(
            RuleSource(
                AverageSource.LEAGUE_ACTIVITY,
                minimum_games=21,
                league_ids=("monday-2025",),
            ),
        ),
    )
    candidates = candidates_from_league_averages(
        [
            league_average("monday-2025", 148, 87),
            league_average("tuesday-2025", 156, 72),
        ]
    )

    decision = evaluate_average_rule(rule, candidates)

    assert decision is not None
    assert decision.average == 148
    assert decision.candidate.league_id == "monday-2025"


def test_falls_back_when_league_average_has_too_few_games() -> None:
    rule = AverageRule(
        "Previous league or composite",
        sources=(
            RuleSource(
                AverageSource.LEAGUE_ACTIVITY,
                minimum_games=21,
                league_ids=("monday-2025",),
            ),
            RuleSource(AverageSource.STANDARD_COMPOSITE),
        ),
    )
    candidates = [
        *candidates_from_league_averages(
            [league_average("monday-2025", 160, 12)]
        ),
        AverageCandidate(
            AverageSource.STANDARD_COMPOSITE,
            153,
            games=188,
            year="2025",
        ),
    ]

    decision = evaluate_average_rule(rule, candidates)

    assert decision is not None
    assert decision.average == 153
    assert decision.source_position == 1


def test_can_exclude_string_pin_league_averages() -> None:
    rule = AverageRule(
        "Highest conventional league average",
        sources=(
            RuleSource(
                AverageSource.LEAGUE_ACTIVITY,
                selection=AverageSelection.HIGHEST,
                allow_string_pin=False,
            ),
        ),
    )
    candidates = candidates_from_league_averages(
        [
            league_average("string", 170, 30, string_pin=True),
            league_average("conventional", 160, 30),
        ]
    )

    decision = evaluate_average_rule(rule, candidates)

    assert decision is not None
    assert decision.average == 160
    assert decision.candidate.league_id == "conventional"


def test_keeps_raw_and_adjusted_league_averages_distinct() -> None:
    candidates = candidates_from_league_averages(
        [league_average("rerated", 160, 30, adjusted_average=172)]
    )
    raw_rule = AverageRule(
        "Raw league average",
        sources=(RuleSource(AverageSource.LEAGUE_ACTIVITY),),
    )
    adjusted_rule = AverageRule(
        "Adjusted league average",
        sources=(RuleSource(AverageSource.ADJUSTED_LEAGUE_ACTIVITY),),
    )

    raw_decision = evaluate_average_rule(raw_rule, candidates)
    adjusted_decision = evaluate_average_rule(adjusted_rule, candidates)

    assert raw_decision is not None
    assert adjusted_decision is not None
    assert raw_decision.average == 160
    assert adjusted_decision.average == 172
