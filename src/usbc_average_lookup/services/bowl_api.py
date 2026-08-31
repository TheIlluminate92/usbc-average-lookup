import json
from collections.abc import Callable, Sequence
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from usbc_average_lookup.models import (
    AverageCondition,
    AverageOption,
    AverageSource,
    CompositeAverage,
    Member,
)
from usbc_average_lookup.services.average_options import composite_options


class BowlApi(Protocol):
    """Contract for the two JSON-backed operations used by the app."""

    def search_members(
        self, name: str = "", membership_id: str = ""
    ) -> Sequence[Member]: ...

    def get_composite_averages(
        self, prefix: str, suffix: str
    ) -> Sequence[CompositeAverage]: ...

    def get_average_options(
        self, prefix: str, suffix: str
    ) -> Sequence[AverageOption]: ...


class UnconfiguredBowlApi:
    """Safe placeholder used until sanitized endpoint details are confirmed."""

    def search_members(
        self, name: str = "", membership_id: str = ""
    ) -> Sequence[Member]:
        raise NotImplementedError("BOWL.com member-search endpoint is not configured yet")

    def get_composite_averages(
        self, prefix: str, suffix: str
    ) -> Sequence[CompositeAverage]:
        raise NotImplementedError("BOWL.com composite-average endpoint is not configured yet")

    def get_average_options(
        self, prefix: str, suffix: str
    ) -> Sequence[AverageOption]:
        raise NotImplementedError("BOWL.com average endpoints are not configured yet")


class AuthenticationExpiredError(RuntimeError):
    pass


class BowlApiError(RuntimeError):
    pass


class HttpBowlApi:
    """Known member-search integration with an in-memory session token.

    The token provider will eventually be supplied by the browser sign-in
    adapter. Tokens are deliberately never persisted by this class.
    """

    BASE_URL = "https://apps1.bowl.com/Mobile/api/v1"

    def __init__(self, token_provider: Callable[[], str], timeout: float = 20.0) -> None:
        self._token_provider = token_provider
        self._timeout = timeout

    def search_members(
        self, name: str = "", membership_id: str = ""
    ) -> Sequence[Member]:
        prefix, suffix = _split_membership_id(membership_id)
        first, last = _split_name(name) if not membership_id else ("", "")
        # BOWL.com exposes name and membership-ID searches at different routes.
        # Sending a name to members/id returns the site's generic administrator
        # error instead of the candidate list shown by its own member-search page.
        path = "members/id" if membership_id else "members/"
        payload = self._get_json(
            path,
            {
                "First": first,
                "Last": last,
                "Prefix": prefix,
                "Suffix": suffix,
                "ANum": "",
                "Zip": "",
                "Radius": "5",
                "State": "",
                "Page": "1",
                "Size": "10",
            },
            allow_unsuccessful=True,
        )
        data = payload.get("data")
        records = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(records, list):
            raise BowlApiError("BOWL.com returned an unexpected member-search response")
        members = [_parse_member(record) for record in records]
        if members:
            return members
        if payload.get("isSuccess") is not True:
            detail = _response_error(payload)
            if detail:
                raise BowlApiError(detail)
        return []

    def get_composite_averages(
        self, prefix: str, suffix: str
    ) -> Sequence[CompositeAverage]:
        payload = self._get_json(
            "compositeaverages",
            {
                "size": "1000",
                "page": "1",
                "prefix": prefix,
                "suffix": suffix,
            },
        )
        data = payload.get("data")
        records = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(records, list):
            raise BowlApiError("BOWL.com returned an unexpected average response")
        return [_parse_composite_average(record) for record in records]

    def get_average_options(
        self, prefix: str, suffix: str
    ) -> Sequence[AverageOption]:
        """Return every observed average source for manual tournament review."""

        options = list(composite_options(self.get_composite_averages(prefix, suffix)))
        league_payload = self._get_json(
            "leagueactivities",
            {"size": "1000", "page": "1", "prefix": prefix, "suffix": suffix},
            allow_unsuccessful=True,
        )
        for index, record in enumerate(_optional_records(league_payload, "league")):
            options.extend(_parse_league_average(record, index))

        rerate_payload = self._get_json(
            "reratedaverage",
            {"size": "1000", "page": "1", "prefix": prefix, "suffix": suffix},
            allow_unsuccessful=True,
        )
        for index, record in enumerate(_optional_records(rerate_payload, "rerate")):
            options.append(_parse_rerated_average(record, index))
        return _deduplicate_options(options)

    def _get_json(
        self,
        path: str,
        parameters: dict[str, str],
        *,
        allow_unsuccessful: bool = False,
    ) -> dict:
        token = self._token_provider()
        if not token:
            raise AuthenticationExpiredError("Sign in to BOWL.com")
        request = Request(
            f"{self.BASE_URL}/{path}?{urlencode(parameters)}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code in (401, 403):
                raise AuthenticationExpiredError("Sign in to BOWL.com again") from error
            raise BowlApiError(f"BOWL.com returned HTTP {error.code}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise BowlApiError("BOWL.com could not be reached") from error
        if not isinstance(payload, dict):
            raise BowlApiError("BOWL.com returned an unexpected response")
        if payload.get("isSuccess") is not True:
            detail = _response_error(payload)
            if allow_unsuccessful:
                return payload
            raise BowlApiError(detail or "BOWL.com did not complete the lookup")
        return payload


def _response_error(payload: dict) -> str:
    """Return a useful service message without exposing request credentials."""

    messages: list[str] = []
    for key in ("validationErrors", "errors"):
        _collect_messages(payload.get(key), messages)
    return "; ".join(dict.fromkeys(messages))


def _collect_messages(value: object, messages: list[str]) -> None:
    if isinstance(value, str):
        if value.strip():
            messages.append(value.strip())
    elif isinstance(value, dict):
        for child in value.values():
            _collect_messages(child, messages)
    elif isinstance(value, list):
        for child in value:
            _collect_messages(child, messages)


def _split_membership_id(membership_id: str) -> tuple[str, str]:
    if not membership_id:
        return "", ""
    pieces = membership_id.strip().split("-", maxsplit=1)
    if len(pieces) != 2 or not all(piece.isdigit() for piece in pieces):
        raise ValueError("Membership ID must look like 1234-567890")
    return pieces[0], pieces[1]


def _split_name(name: str) -> tuple[str, str]:
    pieces = name.strip().split()
    if len(pieces) < 2:
        raise ValueError("Enter both a first and last name")
    return pieces[0], pieces[-1]


def _parse_member(record: dict) -> Member:
    try:
        return Member(
            member_id=str(record["id"]),
            prefix=str(record["prefix"]),
            suffix=str(record["suffix"]),
            first_name=str(record["first"]),
            last_name=str(record["last"]),
            active=bool(record["active"]),
            association=str(record.get("assn", "")),
            association_state=str(record.get("assnstate", "")),
        )
    except (KeyError, TypeError) as error:
        raise BowlApiError("BOWL.com returned an incomplete member record") from error


def _parse_composite_average(record: dict) -> CompositeAverage:
    try:
        return CompositeAverage(
            year=str(record["year"]),
            games=int(record["games"]),
            average=int(record["avg"]),
            sport=bool(record["sport"]),
            challenge=bool(record["challenge"]),
            hand=str(record.get("hand", "")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BowlApiError("BOWL.com returned an incomplete average record") from error


def _parse_league_average(record: dict, index: int = 0) -> list[AverageOption]:
    try:
        average = _record_int(record, "avg", "average", "leagueAverage", "leagueaverage")
    except (TypeError, ValueError) as error:
        raise BowlApiError("BOWL.com returned an incomplete league-average record") from error
    condition = _record_condition(record)
    season = _record_text(record, "year", "season", "seasonYear", "seasonyear")
    games = _record_optional_int(record, "games", "gameCount", "gamecount")
    league = _record_text(
        record,
        "league",
        "leagueName",
        "leaguename",
        "leagueNm",
        "leagueTitle",
        "leagueDescription",
        "lgName",
        "lgname",
        "lname",
        "name",
    ) or _record_descriptive_text(record, "league")
    center = _record_text(
        record,
        "center",
        "centerName",
        "centername",
        "bowlingCenter",
        "cname",
    )
    association = _record_text(
        record,
        "assn",
        "association",
        "associationName",
        "aname",
    )
    hand = _record_text(record, "hand")
    base_key = f"league:{season}:{league}:{average}:{games}:{index}"
    options = [
        AverageOption(
            key=base_key,
            average=average,
            source=AverageSource.LEAGUE,
            condition=condition,
            season=season,
            games=games,
            league=league,
            center=center,
            association=association,
            hand=hand,
        )
    ]
    converted = _record_optional_int(
        record,
        "convAvg",
        "convavg",
        "convertedAverage",
        "convertedaverage",
        "conversionAverage",
        "adjavg",
    )
    if converted is not None and converted > 0 and converted != average:
        options.append(
            AverageOption(
                key=f"converted:{base_key}",
                average=converted,
                source=AverageSource.CONVERTED,
                condition=condition,
                season=season,
                games=games,
                league=league,
                center=center,
                association=association,
                original_average=average,
                hand=hand,
            )
        )
    return options


def _parse_rerated_average(record: dict, index: int = 0) -> AverageOption:
    try:
        average = _record_int(
            record,
            "adjustedAverage",
            "adjustedaverage",
            "reratedAverage",
            "reratedaverage",
            "avg",
            "average",
        )
    except (TypeError, ValueError) as error:
        raise BowlApiError("BOWL.com returned an incomplete rerated-average record") from error
    original = _record_optional_int(
        record,
        "enteringAverage",
        "enteringaverage",
        "originalAverage",
        "originalaverage",
    )
    tournament = _record_text(
        record,
        "tournamentAdjustedIn",
        "tournamentadjustedin",
        "tournament",
        "event",
    )
    adjusted_date = _record_text(record, "dateAdjusted", "dateadjusted", "date")
    adjusted_by = _record_text(record, "adjustedBy", "adjustedby", "assignedBy")
    season = _record_text(record, "year", "season")
    return AverageOption(
        key=f"rerate:{adjusted_date}:{tournament}:{average}:{index}",
        average=average,
        source=AverageSource.RERATE,
        condition=AverageCondition.ADJUSTED,
        season=season,
        original_average=original,
        tournament=tournament,
        adjusted_by=adjusted_by,
        adjusted_date=adjusted_date,
    )


def _response_records(payload: dict, label: str) -> list[dict]:
    data = payload.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = data.get("results", data.get("result", []))
        if isinstance(records, dict):
            records = [records]
        elif records == [] and any(
            key in data
            for key in ("avg", "average", "adjustedAverage", "reratedAverage")
        ):
            records = [data]
    else:
        raise BowlApiError(f"BOWL.com returned an unexpected {label}-average response")
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise BowlApiError(f"BOWL.com returned an unexpected {label}-average response")
    return records


def _optional_records(payload: dict, label: str) -> list[dict]:
    records = _response_records(payload, label)
    if records:
        return records
    if payload.get("isSuccess") is not True:
        detail = _response_error(payload)
        if detail:
            raise BowlApiError(detail)
    return []


def _record_value(record: dict, *keys: str) -> object | None:
    folded = {str(key).casefold(): value for key, value in record.items()}
    for key in keys:
        value = folded.get(key.casefold())
        if value not in (None, ""):
            return value
    return None


def _record_text(record: dict, *keys: str) -> str:
    value = _record_value(record, *keys)
    return "" if value is None else str(value)


def _record_descriptive_text(record: dict, subject: str) -> str:
    """Find an undocumented descriptive text field without accepting IDs/averages."""

    excluded = ("avg", "average", "id", "number", "num", "code", "count")
    for key, value in record.items():
        folded = str(key).casefold()
        is_subject = subject.casefold() in folded or (
            subject == "league" and folded.startswith("lg")
        )
        if (
            is_subject
            and not any(word in folded for word in excluded)
            and isinstance(value, str)
            and value.strip()
        ):
            return value.strip()
    return ""


def _record_int(record: dict, *keys: str) -> int:
    value = _record_value(record, *keys)
    if value is None:
        raise ValueError("missing integer")
    return int(value)


def _record_optional_int(record: dict, *keys: str) -> int | None:
    value = _record_value(record, *keys)
    return None if value is None else int(value)


def _record_condition(record: dict) -> AverageCondition:
    label = _record_text(record, "condition", "laneCondition", "conditionType").casefold()
    if _record_bool(record, "sport") or "sport" in label:
        return AverageCondition.SPORT
    if _record_bool(record, "challenge") or "challenge" in label:
        return AverageCondition.CHALLENGE
    return AverageCondition.STANDARD


def _record_bool(record: dict, *keys: str) -> bool:
    value = _record_value(record, *keys)
    if isinstance(value, str):
        return value.casefold().strip() in {"1", "true", "yes", "y"}
    return bool(value)


def _deduplicate_options(options: list[AverageOption]) -> list[AverageOption]:
    unique: list[AverageOption] = []
    seen: set[tuple[object, ...]] = set()
    for option in options:
        identity = (
            option.source,
            option.average,
            option.games,
            option.season,
            option.league,
            option.tournament,
            option.adjusted_date,
        )
        if identity not in seen:
            unique.append(option)
            seen.add(identity)
    return unique
