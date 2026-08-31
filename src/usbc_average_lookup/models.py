from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LookupStatus(StrEnum):
    REVIEW_REQUIRED = "Review required"
    FOUND = "Found"
    DUPLICATE_ENTRY = "Duplicate entry"
    NOT_FOUND = "Not found"
    MULTIPLE_MATCHES = "Multiple matches"
    NO_AVERAGE = "No average"
    INACTIVE_MEMBER = "Inactive member"
    LOGIN_EXPIRED = "Login expired"
    API_ERROR = "API error"


@dataclass(frozen=True, slots=True)
class InputBowler:
    name: str
    membership_id: str = ""


@dataclass(frozen=True, slots=True)
class Member:
    member_id: str
    prefix: str
    suffix: str
    first_name: str
    last_name: str
    active: bool
    association: str = ""
    association_state: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(frozen=True, slots=True)
class CompositeAverage:
    year: str
    games: int
    average: int
    sport: bool
    challenge: bool
    hand: str = ""


class AverageSource(StrEnum):
    COMPOSITE = "Composite"
    LEAGUE = "League"
    CONVERTED = "Converted league"
    RERATE = "Rerated / adjusted"


class AverageCondition(StrEnum):
    STANDARD = "Standard"
    SPORT = "Sport"
    CHALLENGE = "Challenge"
    ADJUSTED = "Adjusted"


@dataclass(frozen=True, slots=True)
class AverageOption:
    """One average a tournament operator may inspect and select."""

    key: str
    average: int
    source: AverageSource
    condition: AverageCondition
    season: str = ""
    games: int | None = None
    league: str = ""
    center: str = ""
    association: str = ""
    original_average: int | None = None
    tournament: str = ""
    adjusted_by: str = ""
    adjusted_date: str = ""
    hand: str = ""

    @property
    def source_detail(self) -> str:
        if self.source in {AverageSource.LEAGUE, AverageSource.CONVERTED}:
            return self.league_season_label
        if self.source is AverageSource.RERATE:
            return self.tournament or self.source.value
        return f"{self.condition.value} composite"

    @property
    def league_season_label(self) -> str:
        league = self.league or "League name unavailable"
        return f"{league} — {self.season}" if self.season else league


@dataclass(frozen=True, slots=True)
class LookupResult:
    input_name: str
    status: LookupStatus
    membership_id: str = ""
    average: int | None = None
    year: str = ""
    games: int | None = None
    note: str = ""
    member: Member | None = None
    candidates: tuple[Member, ...] = field(default_factory=tuple)
    confirmed_inactive: bool = False
    available_averages: tuple[AverageOption, ...] = field(default_factory=tuple)
    selected_average_key: str = ""

    def __post_init__(self) -> None:
        if (
            self.status in {LookupStatus.FOUND, LookupStatus.REVIEW_REQUIRED}
            and self.average is None
        ):
            raise ValueError("Found and review-required results require an average")
        may_have_average = self.status in {
            LookupStatus.FOUND,
            LookupStatus.REVIEW_REQUIRED,
        } or (
            self.status is LookupStatus.INACTIVE_MEMBER and self.confirmed_inactive
        )
        if not may_have_average and self.average is not None:
            raise ValueError("Only Found or confirmed inactive results may include an average")

    @property
    def needs_attention(self) -> bool:
        return self.needs_resolution or self.needs_review

    @property
    def needs_review(self) -> bool:
        return self.status is LookupStatus.REVIEW_REQUIRED

    @property
    def needs_resolution(self) -> bool:
        return self.status not in {LookupStatus.FOUND, LookupStatus.REVIEW_REQUIRED} and not (
            self.status is LookupStatus.INACTIVE_MEMBER and self.confirmed_inactive
        )

    @property
    def reviewed(self) -> bool:
        return not self.needs_attention
