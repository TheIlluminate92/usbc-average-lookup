import json
from collections.abc import Callable, Sequence
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from usbc_average_lookup.models import CompositeAverage, Member


class BowlApi(Protocol):
    """Contract for the two JSON-backed operations used by the app."""

    def search_members(
        self, name: str = "", membership_id: str = ""
    ) -> Sequence[Member]: ...

    def get_composite_averages(
        self, prefix: str, suffix: str
    ) -> Sequence[CompositeAverage]: ...


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
        payload = self._get_json(
            "members/id",
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
        )
        records = payload.get("data", {}).get("results", [])
        if not isinstance(records, list):
            raise BowlApiError("BOWL.com returned an unexpected member-search response")
        return [_parse_member(record) for record in records]

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
        records = payload.get("data", {}).get("results", [])
        if not isinstance(records, list):
            raise BowlApiError("BOWL.com returned an unexpected average response")
        return [_parse_composite_average(record) for record in records]

    def _get_json(self, path: str, parameters: dict[str, str]) -> dict:
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
        if not isinstance(payload, dict) or payload.get("isSuccess") is not True:
            raise BowlApiError("BOWL.com did not complete the member search")
        return payload


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
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BowlApiError("BOWL.com returned an incomplete average record") from error
