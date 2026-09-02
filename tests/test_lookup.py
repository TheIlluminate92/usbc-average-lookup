from usbc_average_lookup.models import CompositeAverage, InputBowler, LookupStatus, Member
from usbc_average_lookup.services.bowl_api import BowlApiError
from usbc_average_lookup.services.lookup import look_up_bowler, resolve_selected_member


class FakeApi:
    def __init__(self, members=(), averages=()):
        self.members = members
        self.averages = averages

    def search_members(self, name="", membership_id=""):
        return self.members

    def get_composite_averages(self, prefix, suffix):
        return self.averages


def member(*, active=True, suffix="567890"):
    return Member("100", "1234", suffix, "Alex", "Bowler", active)


def average(year="2025", value=187):
    return CompositeAverage(year, 60, value, False, False)


def test_returns_found_with_newest_standard_average() -> None:
    result = look_up_bowler(
        FakeApi([member()], [average("2024", 170), average("2025", 187)]),
        InputBowler("Alex Bowler", "1234-567890"),
    )

    assert result.status is LookupStatus.FOUND
    assert result.average == 187


def test_id_only_lookup_uses_the_member_name_in_results() -> None:
    result = look_up_bowler(
        FakeApi([member()], [average()]),
        InputBowler("", "1234-567890"),
    )

    assert result.input_name == "Alex Bowler"
    assert result.membership_id == "1234-567890"


def test_returns_not_found() -> None:
    result = look_up_bowler(FakeApi(), InputBowler("Missing Bowler"))

    assert result.status is LookupStatus.NOT_FOUND


def test_preserves_api_error_detail_for_the_fixes_screen() -> None:
    class ErrorApi(FakeApi):
        def search_members(self, name="", membership_id=""):
            raise BowlApiError("Narrow the member search")

    result = look_up_bowler(ErrorApi(), InputBowler("Common Bowler"))

    assert result.status is LookupStatus.API_ERROR
    assert result.note == "Narrow the member search"


def test_unexpected_lookup_failure_becomes_reviewable_result() -> None:
    class BrokenApi(FakeApi):
        def search_members(self, name="", membership_id=""):
            raise RuntimeError("internal detail that should not be exported")

    result = look_up_bowler(BrokenApi(), InputBowler("Common Bowler"))

    assert result.status is LookupStatus.API_ERROR
    assert result.needs_attention
    assert result.note == "Unexpected lookup error. Try again or enter a member ID."
    assert "internal detail" not in result.note


def test_replaces_generic_name_search_error_with_actionable_guidance() -> None:
    class ErrorApi(FakeApi):
        def search_members(self, name="", membership_id=""):
            raise BowlApiError(
                "Unexpected error occured, please contact the administrator."
            )

    result = look_up_bowler(ErrorApi(), InputBowler("Common Bowler"))

    assert result.status is LookupStatus.API_ERROR
    assert result.note == (
        "BOWL.com could not resolve this name search. "
        "Enter a membership ID and retry."
    )


def test_returns_multiple_matches() -> None:
    result = look_up_bowler(
        FakeApi([member(), member(suffix="999999")]), InputBowler("Alex Bowler")
    )

    assert result.status is LookupStatus.MULTIPLE_MATCHES
    assert len(result.candidates) == 2


def test_returns_inactive_member() -> None:
    result = look_up_bowler(
        FakeApi([member(active=False)]), InputBowler("Former Bowler")
    )

    assert result.status is LookupStatus.INACTIVE_MEMBER
    assert len(result.candidates) == 1


def test_returns_no_average() -> None:
    result = look_up_bowler(FakeApi([member()]), InputBowler("Alex Bowler"))

    assert result.status is LookupStatus.NO_AVERAGE
    assert result.membership_id == "1234-567890"
    assert result.member == member()


def test_resolves_selected_candidate_without_rerunning_search() -> None:
    selected = member(suffix="999999")
    result = resolve_selected_member(
        FakeApi([member(), selected], [average(value=181)]),
        InputBowler("Alex Bowler"),
        selected,
    )

    assert result.status is LookupStatus.FOUND
    assert result.membership_id == "1234-999999"
    assert result.average == 181
    assert result.year == "2025"
    assert result.games == 60


def test_confirmed_inactive_member_keeps_average_and_leaves_attention_queue() -> None:
    selected = member(active=False)
    result = resolve_selected_member(
        FakeApi([selected], [average(value=150)]),
        InputBowler("Former Bowler"),
        selected,
    )

    assert result.status is LookupStatus.INACTIVE_MEMBER
    assert result.average == 150
    assert result.confirmed_inactive is True
    assert result.needs_attention is False
