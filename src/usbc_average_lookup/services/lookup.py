from collections.abc import Iterable

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus, Member
from usbc_average_lookup.services.average_selector import select_latest_standard
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
    except BowlApiError:
        return _result(bowler, LookupStatus.API_ERROR, "BOWL.com could not complete this lookup")
    except ValueError as error:
        return _result(bowler, LookupStatus.API_ERROR, str(error))


def look_up_all(api: BowlApi, bowlers: Iterable[InputBowler]) -> list[LookupResult]:
    return [look_up_bowler(api, bowler) for bowler in bowlers]


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
            "Only an inactive membership was found",
            member=matches[0] if len(matches) == 1 else None,
        )
    if len(active) > 1:
        return _result(
            bowler,
            LookupStatus.MULTIPLE_MATCHES,
            f"Choose from {len(active)} active members",
        )

    member = active[0]
    averages = api.get_composite_averages(member.prefix, member.suffix)
    selected = select_latest_standard(averages)
    if selected is None:
        return _result(
            bowler,
            LookupStatus.NO_AVERAGE,
            "Member found, but no standard composite average is available",
            member=member,
        )
    return LookupResult(
        input_name=bowler.name,
        status=LookupStatus.FOUND,
        membership_id=bowler.membership_id or f"{member.prefix}-{member.suffix}",
        average=selected.average,
        note=f"{selected.year} standard composite, {selected.games} games",
        member=member,
    )


def _result(
    bowler: InputBowler,
    status: LookupStatus,
    note: str,
    member: Member | None = None,
) -> LookupResult:
    return LookupResult(
        input_name=bowler.name,
        status=status,
        membership_id=bowler.membership_id,
        note=note,
        member=member,
    )
