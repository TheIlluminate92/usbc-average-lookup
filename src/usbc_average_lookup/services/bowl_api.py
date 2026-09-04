import json
from collections.abc import Callable, Sequence
from threading import Event
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from usbc_average_lookup.models import CompositeAverage, LeagueAverage, Member
from usbc_average_lookup.services.sanitize import sanitize


class BowlApi(Protocol):
    """Contract for the two JSON-backed operations used by the app."""

    def search_members(
        self, name: str = "", membership_id: str = "", *, state: str = "", zip_code: str = ""
    ) -> Sequence[Member]: ...

    def get_composite_averages(self, prefix: str, suffix: str) -> Sequence[CompositeAverage]: ...


class UnconfiguredBowlApi:
    """Safe placeholder used until sanitized endpoint details are confirmed."""

    def search_members(self, name: str = "", membership_id: str = "") -> Sequence[Member]:
        raise NotImplementedError("BOWL.com member-search endpoint is not configured yet")

    def get_composite_averages(self, prefix: str, suffix: str) -> Sequence[CompositeAverage]:
        raise NotImplementedError("BOWL.com composite-average endpoint is not configured yet")


class AuthenticationExpiredError(RuntimeError):
    pass


class BowlApiError(RuntimeError):
    pass


class RateLimitedError(BowlApiError):
    pass


class ApiCancelledError(RuntimeError):
    pass


class IncompleteMemberSearchError(BowlApiError):
    def __init__(self, members: Sequence[Member], detail: str):
        super().__init__(detail)
        self.members = list(members)


class HttpBowlApi:
    """Known member-search integration with an in-memory session token.

    The token provider will eventually be supplied by the browser sign-in
    adapter. Tokens are deliberately never persisted by this class.
    """

    BASE_URL = "https://apps1.bowl.com/Mobile/api/v1"

    def __init__(
        self, token_provider: Callable[[], str], timeout: float = 20.0, cancel: Event | None = None
    ) -> None:
        self._token_provider = token_provider
        self._timeout = timeout
        self._cancel = cancel
        self.snapshots: dict[str, object] = {}

    def _pages(
        self,
        path: str,
        parameters: dict[str, str],
        *,
        allow_unsuccessful: bool = False,
        on_page: Callable[[list[dict]], None] | None = None,
    ) -> list[dict]:
        """Collect every reported page; incomplete pagination is never a success."""
        records: list[dict] = []
        pages: list[dict] = []
        page_key = "Page" if "Page" in parameters else "page"
        for page in range(1, 1001):
            if self._cancel is not None and self._cancel.is_set():
                raise ApiCancelledError()
            payload = self._get_json(
                path, {**parameters, page_key: str(page)}, allow_unsuccessful=allow_unsuccessful
            )
            data = payload.get("data")
            if not isinstance(data, dict) and payload.get("isSuccess") is True:
                raise BowlApiError("BOWL.com returned an unexpected response")
            rows = data.get("results") if isinstance(data, dict) else []
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise BowlApiError("BOWL.com returned an unexpected response")
            if not rows and payload.get("isSuccess") is not True:
                detail = _response_error(payload)
                if detail:
                    raise BowlApiError(str(sanitize(detail)))
            if rows and any(previous.get("data", {}).get("results") == rows for previous in pages):
                raise BowlApiError("BOWL.com repeated a page; narrow the search and retry")
            pages.append(sanitize(payload))
            records.extend(rows)
            if on_page:
                on_page(rows)
            try:
                total = (
                    data.get("totalPages", data.get("TotalPages", 1))
                    if isinstance(data, dict)
                    else 1
                )
                if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                    raise ValueError("Invalid page count")
            except (ValueError, TypeError) as error:
                raise BowlApiError("BOWL.com returned invalid pagination") from error
            if page >= total:
                self.snapshots[path] = pages
                return records
            if not rows:
                raise BowlApiError("BOWL.com returned an incomplete page; retry refresh")
        raise BowlApiError("BOWL.com returned too many pages; narrow the search")

    def search_members(
        self, name: str = "", membership_id: str = "", *, state: str = "", zip_code: str = ""
    ) -> Sequence[Member]:
        prefix, suffix = _split_membership_id(membership_id)
        first, last = _split_name(name) if not membership_id else ("", "")
        # BOWL.com exposes name and membership-ID searches at different routes.
        # Sending a name to members/id returns the site's generic administrator
        # error instead of the candidate list shown by its own member-search page.
        path = "members/id" if membership_id else "members/"
        members: list[Member] = []

        def collect(rows):
            members.extend([_parse_member(record) for record in rows])

        try:
            self._pages(
                path,
                {
                    "First": first,
                    "Last": last,
                    "Prefix": prefix,
                    "Suffix": suffix,
                    "ANum": "",
                    "Zip": zip_code if not membership_id else "",
                    "Radius": "5",
                    "State": state if not membership_id else "",
                    "Page": "1",
                    # Use the same small pages as BOWL.com's member-search page.
                    "Size": "10",
                },
                allow_unsuccessful=True,
                on_page=collect,
            )
        except RateLimitedError:
            raise
        except BowlApiError as error:
            detail = str(error)
            if not membership_id:
                detail += ". Open Resolve identity to narrow by state or ZIP, or enter a USBC ID."
                if members:
                    raise IncompleteMemberSearchError(members, detail) from error
            raise BowlApiError(detail) from error
        return members

    def get_composite_averages(self, prefix: str, suffix: str) -> Sequence[CompositeAverage]:
        records = self._pages(
            "compositeaverages",
            {
                "size": "1000",
                "page": "1",
                "prefix": prefix,
                "suffix": suffix,
            },
        )
        return [_parse_composite_average(record) for record in records]

    def get_league_averages(self, prefix: str, suffix: str) -> Sequence[LeagueAverage]:
        records = self._pages(
            "leagueactivities", {"size": "1000", "page": "1", "prefix": prefix, "suffix": suffix}
        )
        return [_parse_league_average(record) for record in records]

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
            if error.code == 429:
                raise RateLimitedError(
                    "BOWL.com rate limit reached; wait before refreshing again"
                ) from error
            if error.code in (401, 403):
                raise AuthenticationExpiredError("Sign in to BOWL.com again") from error
            raise BowlApiError(f"BOWL.com returned HTTP {error.code}") from error
        except TimeoutError as error:
            raise BowlApiError("BOWL.com took too long to respond") from error
        except (URLError, json.JSONDecodeError) as error:
            raise BowlApiError("BOWL.com could not be reached") from error
        if not isinstance(payload, dict):
            raise BowlApiError("BOWL.com returned an unexpected response")
        if payload.get("isSuccess") is not True:
            detail = _response_error(payload)
            if allow_unsuccessful:
                return payload
            raise BowlApiError(str(sanitize(detail)) or "BOWL.com did not complete the lookup")
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
            active=_required_boolean(record, "active"),
            association=str(record.get("assn", "")),
            association_state=str(record.get("assnstate", "")),
            middle_initial=str(record.get("init") or ""),
            gender=str(record.get("gender") or ""),
            membership_from=str(record.get("from") or ""),
            membership_thru=str(record.get("thru") or ""),
            product=str(record.get("prod") or ""),
            flags={
                key: value for key, value in sanitize(record).items() if isinstance(value, bool)
            },
            raw=sanitize(record),
        )
    except (KeyError, TypeError) as error:
        raise BowlApiError("BOWL.com returned an incomplete member record") from error


def _required_boolean(record: dict, field: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise BowlApiError(f"BOWL.com returned an invalid {field} flag")
    return value


def _parse_league_average(record: dict) -> LeagueAverage:
    try:
        return LeagueAverage(
            league_id=str(record["lid"]),
            league_name=str(record["lname"]),
            season=str(record["season"]),
            center_id=str(record["cid"]),
            center_name=str(record["cname"]),
            association_id=str(record["aid"]),
            association_name=str(record["aname"]),
            association_number=str(record["anum"]),
            year=str(record["year"]),
            average=int(record["avg"]),
            games=int(record["games"]),
            sport=_required_boolean(record, "sport"),
            challenge=_required_boolean(record, "challenge"),
            roll_and_grow=_required_boolean(record, "rollngrow"),
            bumper=_required_boolean(record, "bumper"),
            string_pin=_required_boolean(record, "stringpin"),
            pattern=str(record.get("pattern") or ""),
            hand=str(record.get("hand") or ""),
            adjusted_average=int(record.get("adjavg") or 0),
            raw=sanitize(record),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BowlApiError("BOWL.com returned an incomplete league-average record") from error


def _parse_composite_average(record: dict) -> CompositeAverage:
    try:
        return CompositeAverage(
            year=str(record["year"]),
            games=int(record["games"]),
            average=int(record["avg"]),
            sport=_required_boolean(record, "sport"),
            challenge=_required_boolean(record, "challenge"),
            hand=str(record.get("hand") or ""),
            raw=sanitize(record),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BowlApiError("BOWL.com returned an incomplete average record") from error
