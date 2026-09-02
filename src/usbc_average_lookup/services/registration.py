from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus


class CompetitionKind(StrEnum):
    LEAGUE = "League"
    TOURNAMENT = "Tournament"


class VerificationState(StrEnum):
    NOT_CHECKED = "Not checked"
    CHECKING = "Checking"
    VERIFIED = "Verified"
    NEEDS_REVIEW = "Needs review"
    NOT_FOUND = "Not found"
    NO_AVERAGE = "No average"
    ERROR = "Lookup error"


@dataclass(slots=True)
class Competition:
    id: str
    name: str
    season: str
    kind: CompetitionKind
    created_at: str
    archived: bool = False

    @property
    def display_name(self) -> str:
        return f"{self.season}  •  {self.name}" if self.season else self.name

    @property
    def selection_label(self) -> str:
        return f"{self.display_name}  [{self.kind.value}]"


@dataclass(slots=True)
class BowlerProfile:
    id: str
    name: str
    membership_id: str = ""


@dataclass(slots=True)
class Team:
    id: str
    competition_id: str
    name: str


@dataclass(slots=True)
class Registration:
    id: str
    competition_id: str
    bowler_id: str
    team_id: str = ""
    verification: VerificationState = VerificationState.NOT_CHECKED
    average: int | None = None
    average_year: str = ""
    games: int | None = None
    note: str = ""
    withdrawn: bool = False
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class RegistrationView:
    registration: Registration
    bowler: BowlerProfile
    team: Team | None

    @property
    def status(self) -> str:
        if self.registration.withdrawn:
            return "Withdrawn"
        if self.team is None:
            return "Unassigned team"
        if self.registration.verification is VerificationState.VERIFIED:
            return "Ready"
        if self.registration.verification is VerificationState.CHECKING:
            return "Looking up average"
        if self.registration.verification is VerificationState.NEEDS_REVIEW:
            return "Multiple matches — review"
        if self.registration.verification is VerificationState.NOT_FOUND:
            return "Bowler not found"
        if self.registration.verification is VerificationState.NO_AVERAGE:
            return "No average available"
        if self.registration.verification is VerificationState.ERROR:
            return "Lookup error"
        if not self.bowler.membership_id:
            return "Missing member ID"
        return "Not checked"


class RegistrationDataError(ValueError):
    pass


def default_registration_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".average-assistant"
    return root / "Bowling Manager" / "registration-data.json"


class RegistrationStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_registration_path()
        self.competitions: list[Competition] = []
        self.bowlers: list[BowlerProfile] = []
        self.teams: list[Team] = []
        self.registrations: list[Registration] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("schemaVersion") != self.SCHEMA_VERSION:
                raise RegistrationDataError("Registration data uses an unsupported version")
            self.competitions = [
                Competition(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    season=str(item.get("season", "")),
                    kind=CompetitionKind(item["kind"]),
                    created_at=str(item.get("created_at", "")),
                    archived=bool(item.get("archived", False)),
                )
                for item in document.get("competitions", [])
            ]
            self.bowlers = [BowlerProfile(**item) for item in document.get("bowlers", [])]
            self.teams = [Team(**item) for item in document.get("teams", [])]
            self.registrations = [
                Registration(
                    **{
                        **item,
                        "verification": VerificationState(
                            VerificationState.NOT_CHECKED
                            if item.get("verification") == VerificationState.CHECKING
                            else item.get("verification", VerificationState.NOT_CHECKED)
                        ),
                    }
                )
                for item in document.get("registrations", [])
            ]
            self._validate_references()
        except (
            AttributeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            if isinstance(error, RegistrationDataError):
                raise
            raise RegistrationDataError(
                f"Registration data could not be read: {error}"
            ) from error

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": self.SCHEMA_VERSION,
            "savedAt": _now(),
            "competitions": [_serialized(item) for item in self.competitions],
            "bowlers": [_serialized(item) for item in self.bowlers],
            "teams": [_serialized(item) for item in self.teams],
            "registrations": [_serialized(item) for item in self.registrations],
        }
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(document, temporary, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(self.path)

    def add_competition(
        self, name: str, season: str, kind: CompetitionKind
    ) -> Competition:
        clean_name = _required(name, "League or tournament name")
        clean_season = season.strip()
        duplicate = next(
            (
                item
                for item in self.competitions
                if item.kind is kind
                and _key(item.name) == _key(clean_name)
                and _key(item.season) == _key(clean_season)
            ),
            None,
        )
        if duplicate:
            raise RegistrationDataError(f"{duplicate.display_name} already exists")
        competition = Competition(
            id=_new_id(),
            name=clean_name,
            season=clean_season,
            kind=kind,
            created_at=_now(),
        )
        self.competitions.append(competition)
        self.save()
        return competition

    def add_team(self, competition_id: str, name: str) -> Team:
        self._competition(competition_id)
        clean_name = _required(name, "Team name")
        if any(
            team.competition_id == competition_id and _key(team.name) == _key(clean_name)
            for team in self.teams
        ):
            raise RegistrationDataError(f"Team {clean_name!r} already exists")
        team = Team(_new_id(), competition_id, clean_name)
        self.teams.append(team)
        self.save()
        return team

    def update_competition(
        self,
        competition_id: str,
        name: str,
        season: str,
        kind: CompetitionKind,
    ) -> None:
        competition = self._competition(competition_id)
        clean_name = _required(name, "League or tournament name")
        clean_season = season.strip()
        if any(
            item.id != competition_id
            and item.kind is kind
            and _key(item.name) == _key(clean_name)
            and _key(item.season) == _key(clean_season)
            for item in self.competitions
        ):
            raise RegistrationDataError(
                f"{clean_season + ' • ' if clean_season else ''}{clean_name} already exists"
            )
        competition.name = clean_name
        competition.season = clean_season
        competition.kind = kind
        self.save()

    def set_competition_archived(self, competition_id: str, archived: bool) -> None:
        self._competition(competition_id).archived = archived
        self.save()

    def list_teams(self, competition_id: str) -> list[Team]:
        return sorted(
            (team for team in self.teams if team.competition_id == competition_id),
            key=lambda item: _key(item.name),
        )

    def rename_team(self, team_id: str, name: str) -> None:
        team = self._team(team_id)
        clean_name = _required(name, "Team name")
        if any(
            item.id != team_id
            and item.competition_id == team.competition_id
            and _key(item.name) == _key(clean_name)
            for item in self.teams
        ):
            raise RegistrationDataError(f"Team {clean_name!r} already exists")
        team.name = clean_name
        self.save()

    def update_bowler_profile(
        self, bowler_id: str, name: str, membership_id: str
    ) -> None:
        bowler = self._bowler(bowler_id)
        clean_name = _required(name, "Bowler name")
        clean_id = membership_id.strip()
        if clean_id and any(
            item.id != bowler_id
            and item.membership_id
            and _membership_key(item.membership_id) == _membership_key(clean_id)
            for item in self.bowlers
        ):
            raise RegistrationDataError(
                f"Member ID {clean_id} already belongs to another player"
            )
        identity_changed = (
            _key(bowler.name) != _key(clean_name)
            or _membership_key(bowler.membership_id) != _membership_key(clean_id)
        )
        bowler.name = clean_name
        bowler.membership_id = clean_id
        if identity_changed:
            for registration in self.registrations:
                if registration.bowler_id == bowler_id:
                    registration.verification = VerificationState.NOT_CHECKED
                    registration.average = None
                    registration.average_year = ""
                    registration.games = None
                    registration.note = "Player identity changed; check the average again"
        self.save()

    def register_bowler(
        self,
        competition_id: str,
        name: str,
        membership_id: str = "",
        team_id: str = "",
    ) -> Registration:
        registration = self._register_bowler(
            competition_id, name, membership_id, team_id
        )
        self.save()
        return registration

    def register_team(
        self,
        competition_id: str,
        team_name: str,
        bowlers: list[InputBowler],
    ) -> tuple[Team, list[Registration]]:
        if not bowlers:
            raise RegistrationDataError("Enter at least one bowler")
        snapshot = (
            deepcopy(self.bowlers),
            deepcopy(self.teams),
            deepcopy(self.registrations),
        )
        try:
            existing = next(
                (
                    team
                    for team in self.list_teams(competition_id)
                    if _key(team.name) == _key(team_name)
                ),
                None,
            )
            team = existing or Team(
                _new_id(), competition_id, _required(team_name, "Team name")
            )
            if existing is None:
                self.teams.append(team)
            registrations = [
                self._register_bowler(
                    competition_id, bowler.name, bowler.membership_id, team.id
                )
                for bowler in bowlers
            ]
            self.save()
            return team, registrations
        except Exception:
            self.bowlers, self.teams, self.registrations = snapshot
            raise

    def registration_views(self, competition_id: str) -> list[RegistrationView]:
        bowler_by_id = {bowler.id: bowler for bowler in self.bowlers}
        team_by_id = {team.id: team for team in self.teams}
        return sorted(
            (
                RegistrationView(
                    registration,
                    bowler_by_id[registration.bowler_id],
                    team_by_id.get(registration.team_id),
                )
                for registration in self.registrations
                if registration.competition_id == competition_id
            ),
            key=lambda item: (
                item.registration.withdrawn,
                _key(item.team.name) if item.team else "zzzz",
                _key(item.bowler.name),
            ),
        )

    def mark_checking(self, registration_id: str) -> None:
        self.mark_checking_many([registration_id])

    def mark_checking_many(self, registration_ids: list[str]) -> None:
        for registration_id in registration_ids:
            registration = self._registration(registration_id)
            registration.verification = VerificationState.CHECKING
            registration.note = "Waiting for BOWL.com"
        self.save()

    def apply_lookup_result(self, registration_id: str, result: LookupResult) -> None:
        registration = self._registration(registration_id)
        bowler = self._bowler(registration.bowler_id)
        if result.membership_id:
            bowler.membership_id = result.membership_id
        registration.average = result.average
        registration.average_year = result.year
        registration.games = result.games
        registration.note = result.note
        if result.status is LookupStatus.FOUND or result.confirmed_inactive:
            registration.verification = VerificationState.VERIFIED
        elif result.status is LookupStatus.MULTIPLE_MATCHES:
            registration.verification = VerificationState.NEEDS_REVIEW
        elif result.status is LookupStatus.NOT_FOUND:
            registration.verification = VerificationState.NOT_FOUND
        elif result.status is LookupStatus.NO_AVERAGE:
            registration.verification = VerificationState.NO_AVERAGE
        else:
            registration.verification = VerificationState.ERROR
        self.save()

    def assign_team(self, registration_id: str, team_id: str) -> None:
        registration = self._registration(registration_id)
        if team_id:
            team = self._team(team_id)
            if team.competition_id != registration.competition_id:
                raise RegistrationDataError("That team belongs to another competition")
        registration.team_id = team_id
        self.save()

    def update_registration(
        self,
        registration_id: str,
        name: str,
        membership_id: str,
        team_id: str,
    ) -> None:
        registration = self._registration(registration_id)
        current_bowler = self._bowler(registration.bowler_id)
        clean_name = _required(name, "Bowler name")
        clean_id = membership_id.strip()
        if team_id:
            team = self._team(team_id)
            if team.competition_id != registration.competition_id:
                raise RegistrationDataError("That team belongs to another competition")

        target = None
        if clean_id:
            target = next(
                (
                    bowler
                    for bowler in self.bowlers
                    if bowler.id != current_bowler.id
                    and bowler.membership_id
                    and _membership_key(bowler.membership_id)
                    == _membership_key(clean_id)
                ),
                None,
            )
        if target is not None:
            if any(
                item.id != registration.id
                and item.competition_id == registration.competition_id
                and item.bowler_id == target.id
                for item in self.registrations
            ):
                raise RegistrationDataError(
                    f"Member ID {clean_id} is already registered in this competition"
                )
            registration.bowler_id = target.id
            target.name = clean_name
            registration.verification = VerificationState.NOT_CHECKED
            registration.average = None
            registration.average_year = ""
            registration.games = None
            registration.note = "Identity changed; check the average again"
            if not any(
                item.bowler_id == current_bowler.id for item in self.registrations
            ):
                self.bowlers.remove(current_bowler)
        else:
            identity_changed = (
                _key(current_bowler.name) != _key(clean_name)
                or _membership_key(current_bowler.membership_id)
                != _membership_key(clean_id)
            )
            current_bowler.name = clean_name
            current_bowler.membership_id = clean_id
            if identity_changed:
                registration.verification = VerificationState.NOT_CHECKED
                registration.average = None
                registration.average_year = ""
                registration.games = None
                registration.note = "Identity changed; check the average again"
        registration.team_id = team_id
        self.save()

    def set_withdrawn(self, registration_id: str, withdrawn: bool) -> None:
        self._registration(registration_id).withdrawn = withdrawn
        self.save()

    def _register_bowler(
        self,
        competition_id: str,
        name: str,
        membership_id: str,
        team_id: str,
    ) -> Registration:
        self._competition(competition_id)
        clean_name = _required(name, "Bowler name")
        clean_id = membership_id.strip()
        if team_id:
            team = self._team(team_id)
            if team.competition_id != competition_id:
                raise RegistrationDataError("That team belongs to another competition")
        bowler = self._find_bowler(clean_name, clean_id)
        if bowler is None:
            bowler = BowlerProfile(_new_id(), clean_name, clean_id)
            self.bowlers.append(bowler)
        elif clean_id and not bowler.membership_id:
            bowler.membership_id = clean_id
        if any(
            item.competition_id == competition_id and item.bowler_id == bowler.id
            for item in self.registrations
        ):
            raise RegistrationDataError(f"{bowler.name} is already registered")
        registration = Registration(
            id=_new_id(),
            competition_id=competition_id,
            bowler_id=bowler.id,
            team_id=team_id,
            created_at=_now(),
        )
        self.registrations.append(registration)
        return registration

    def _find_bowler(self, name: str, membership_id: str) -> BowlerProfile | None:
        if membership_id:
            member_key = _membership_key(membership_id)
            member_match = next(
                (
                    bowler
                    for bowler in self.bowlers
                    if bowler.membership_id
                    and _membership_key(bowler.membership_id) == member_key
                ),
                None,
            )
            if member_match:
                return member_match
            # Two people may share a name. A different known ID must create a new profile.
            named = [bowler for bowler in self.bowlers if _key(bowler.name) == _key(name)]
            return next((bowler for bowler in named if not bowler.membership_id), None)
        named = [bowler for bowler in self.bowlers if _key(bowler.name) == _key(name)]
        return named[0] if len(named) == 1 else None

    def _validate_references(self) -> None:
        competition_ids = {item.id for item in self.competitions}
        bowler_ids = {item.id for item in self.bowlers}
        team_ids = {item.id for item in self.teams}
        if any(team.competition_id not in competition_ids for team in self.teams):
            raise RegistrationDataError("Registration data contains an orphaned team")
        for registration in self.registrations:
            if (
                registration.competition_id not in competition_ids
                or registration.bowler_id not in bowler_ids
                or registration.team_id
                and registration.team_id not in team_ids
            ):
                raise RegistrationDataError("Registration data contains an orphaned entry")

    def _competition(self, item_id: str) -> Competition:
        return _find(self.competitions, item_id, "competition")

    def _bowler(self, item_id: str) -> BowlerProfile:
        return _find(self.bowlers, item_id, "bowler")

    def _team(self, item_id: str) -> Team:
        return _find(self.teams, item_id, "team")

    def _registration(self, item_id: str) -> Registration:
        return _find(self.registrations, item_id, "registration")


def _find(items: list, item_id: str, label: str):
    item = next((candidate for candidate in items if candidate.id == item_id), None)
    if item is None:
        raise RegistrationDataError(f"Unknown {label}")
    return item


def _serialized(item: object) -> dict:
    return asdict(item)


def _required(value: str, label: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise RegistrationDataError(f"{label} is required")
    return cleaned


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _membership_key(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", value.casefold())


def _new_id() -> str:
    return uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat()
