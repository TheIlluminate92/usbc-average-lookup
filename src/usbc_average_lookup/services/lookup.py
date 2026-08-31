from collections.abc import Iterable
from dataclasses import replace

from usbc_average_lookup.models import (
    AverageOption,
    InputBowler,
    LookupResult,
    LookupStatus,
    Member,
)
from usbc_average_lookup.services.average_options import suggested_option
from usbc_average_lookup.services.bowl_api import (
    AuthenticationExpiredError,
    BowlApi,
    BowlApiError,
)


def look_up_bowler(api: BowlApi, bowler: InputBowler) -> LookupResult:
    try:
        matches = list(api.search_members(bowler.name, bowler.membership_id))
        return _resolve_matches(api, bowler, matches)
    except AuthenticationExpiredError:
        return _result(bowler, LookupStatus.LOGIN_EXPIRED, "Sign in to BOWL.com again")
    except BowlApiError as error:
        return _result(
            bowler,
            LookupStatus.API_ERROR,
            _lookup_error_note(bowler, error),
        )
    except ValueError as error:
        return _result(bowler, LookupStatus.API_ERROR, str(error))


def look_up_all(api: BowlApi, bowlers: Iterable[InputBowler]) -> list[LookupResult]:
    return [look_up_bowler(api, bowler) for bowler in bowlers]


def resolve_selected_member(
    api: BowlApi, bowler: InputBowler, member: Member
) -> LookupResult:
    try:
        return resolve_member(api, bowler, member)
    except AuthenticationExpiredError:
        return _result(bowler, LookupStatus.LOGIN_EXPIRED, "Sign in to BOWL.com again")
    except BowlApiError as error:
        return _result(
            bowler,
            LookupStatus.API_ERROR,
            str(error) or "BOWL.com could not complete this lookup",
            member=member,
        )
    except ValueError as error:
        return _result(bowler, LookupStatus.API_ERROR, str(error), member=member)


def _resolve_matches(
    api: BowlApi, bowler: InputBowler, matches: list[Member]
) -> LookupResult:
    if not matches:
        return _result(bowler, LookupStatus.NOT_FOUND, "Check the name or membership ID")

    active = [member for member in matches if member.active]
    if not active:
        return _result(
            bowler,
            LookupStatus.INACTIVE_MEMBER,
            "Confirm the inactive member or search again",
            member=matches[0] if len(matches) == 1 else None,
            candidates=matches,
        )
    if len(active) > 1:
        return _result(
            bowler,
            LookupStatus.MULTIPLE_MATCHES,
            f"Choose from {len(active)} active members",
            candidates=active,
        )

    return resolve_member(api, bowler, active[0])


def resolve_member(api: BowlApi, bowler: InputBowler, member: Member) -> LookupResult:
    """Complete one result after the user selects a specific member."""

    averages = tuple(api.get_average_options(member.prefix, member.suffix))
    selected = suggested_option(averages) or (averages[0] if averages else None)
    if selected is None:
        return _result(
            bowler,
            LookupStatus.NO_AVERAGE,
            "Member found, but BOWL.com returned no selectable averages",
            member=member,
        )
    return LookupResult(
        input_name=bowler.name or member.display_name,
        status=LookupStatus.REVIEW_REQUIRED,
        membership_id=bowler.membership_id or f"{member.prefix}-{member.suffix}",
        average=selected.average,
        year=selected.season,
        games=selected.games,
        note="Review and confirm an average before export",
        member=member,
        available_averages=averages,
        selected_average_key=selected.key,
    )


def confirm_average(result: LookupResult, selected: AverageOption) -> LookupResult:
    """Record the operator's explicit choice for one bowler."""

    if selected not in result.available_averages:
        raise ValueError("The selected average is not available for this bowler")
    inactive = result.member is not None and not result.member.active
    games = f", {selected.games} games" if selected.games is not None else ""
    season = f" — {selected.season}" if selected.season else ""
    return replace(
        result,
        status=LookupStatus.INACTIVE_MEMBER if inactive else LookupStatus.FOUND,
        average=selected.average,
        year=selected.season,
        games=selected.games,
        note=f"Confirmed: {selected.source_detail}{season}{games}",
        selected_average_key=selected.key,
        confirmed_inactive=inactive,
    )


def _result(
    bowler: InputBowler,
    status: LookupStatus,
    note: str,
    member: Member | None = None,
    candidates: list[Member] | None = None,
) -> LookupResult:
    return LookupResult(
        input_name=bowler.name or bowler.membership_id,
        status=status,
        membership_id=bowler.membership_id,
        note=note,
        member=member,
        candidates=tuple(candidates or ()),
    )


def _lookup_error_note(bowler: InputBowler, error: BowlApiError) -> str:
    message = str(error).strip()
    if not bowler.membership_id and "unexpected error" in message.casefold():
        return "BOWL.com could not resolve this name search. Enter a membership ID and retry."
    return message or "BOWL.com could not complete this lookup"
