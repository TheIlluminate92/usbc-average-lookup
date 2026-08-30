from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LookupStatus(StrEnum):
    FOUND = "Found"
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


@dataclass(frozen=True, slots=True)
class LookupResult:
    input_name: str
    status: LookupStatus
    membership_id: str = ""
    average: int | None = None
    note: str = ""
    member: Member | None = None

    def __post_init__(self) -> None:
        if self.status is LookupStatus.FOUND and self.average is None:
            raise ValueError("Found results require an average")
        if self.status is not LookupStatus.FOUND and self.average is not None:
            raise ValueError("Only Found results may include an average")
