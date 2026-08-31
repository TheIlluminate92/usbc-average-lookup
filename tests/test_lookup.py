from usbc_average_lookup.models import CompositeAverage, InputBowler, LookupStatus, Member
from usbc_average_lookup.services.average_options import composite_options
from usbc_average_lookup.services.bowl_api import BowlApiError
from usbc_average_lookup.services.lookup import (
    confirm_average,
    find_duplicate_inputs,
    flag_duplicate_results,
    look_up_all,
    look_up_bowler,
    resolve_selected_member,
)


class FakeApi:
    def __init__(self, members=(), averages=()):
        self.members = members
        self.averages = averages

    def search_members(self, name="", membership_id=""):
        return self.members

    def get_composite_averages(self, prefix, suffix):
        return self.averages

    def get_average_options(self, prefix, suffix):
        return composite_options(self.averages)


def member(*, active=True, suffix="567890"):
    return Member("100", "1234", suffix, "Alex", "Bowler", active)


def average(year="2025", value=187):
    return CompositeAverage(year, 60, value, False, False)


def test_returns_suggested_average_that_requires_review() -> None:
    result = look_up_bowler(
        FakeApi([member()], [average("2024", 170), average("2025", 187)]),
        InputBowler("Alex Bowler", "1234-567890"),
    )

    assert result.status is LookupStatus.REVIEW_REQUIRED
    assert result.average == 187
    assert result.needs_review is True


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


def test_resolves_selected_candidate_without_rerunning_search() -> None:
    selected = member(suffix="999999")
    result = resolve_selected_member(
        FakeApi([member(), selected], [average(value=181)]),
        InputBowler("Alex Bowler"),
        selected,
    )

    assert result.status is LookupStatus.REVIEW_REQUIRED
    assert result.membership_id == "1234-999999"
    assert result.average == 181
    assert result.year == "2025"
    assert result.games == 60


def test_inactive_member_requires_average_review_then_leaves_attention_queue() -> None:
    selected = member(active=False)
    result = resolve_selected_member(
        FakeApi([selected], [average(value=150)]),
        InputBowler("Former Bowler"),
        selected,
    )

    assert result.status is LookupStatus.REVIEW_REQUIRED
    assert result.average == 150
    assert result.confirmed_inactive is False
    assert result.needs_attention is True

    confirmed = confirm_average(result, result.available_averages[0])

    assert confirmed.status is LookupStatus.INACTIVE_MEMBER
    assert confirmed.confirmed_inactive is True
    assert confirmed.needs_attention is False


def test_active_member_does_not_become_ready_without_explicit_confirmation() -> None:
    result = look_up_bowler(
        FakeApi([member()], [average(value=181)]), InputBowler("Alex Bowler")
    )

    confirmed = confirm_average(result, result.available_averages[0])

    assert result.status is LookupStatus.REVIEW_REQUIRED
    assert confirmed.status is LookupStatus.FOUND
    assert confirmed.reviewed is True


def test_duplicate_membership_ids_are_flagged_before_any_api_lookup() -> None:
    class CountingApi(FakeApi):
        def __init__(self):
            super().__init__([member()], [average()])
            self.search_count = 0

        def search_members(self, name="", membership_id=""):
            self.search_count += 1
            return super().search_members(name, membership_id)

    api = CountingApi()
    bowlers = [
        InputBowler("Alex Bowler", "1234-567890"),
        InputBowler("Alex Bowler", "1234567890"),
    ]

    results = look_up_all(api, bowlers)

    assert [result.status for result in results] == [
        LookupStatus.DUPLICATE_ENTRY,
        LookupStatus.DUPLICATE_ENTRY,
    ]
    assert api.search_count == 0
    assert "#1, #2" in results[0].note


def test_same_name_without_ids_requires_attention() -> None:
    bowlers = [InputBowler("David Brown"), InputBowler("  david   brown  ")]

    duplicate_notes = find_duplicate_inputs(bowlers)

    assert set(duplicate_notes) == {0, 1}
    assert "without membership IDs" in duplicate_notes[0]


def test_same_name_with_different_ids_is_allowed() -> None:
    bowlers = [
        InputBowler("David Brown", "1111-111111"),
        InputBowler("David Brown", "2222-222222"),
    ]

    assert find_duplicate_inputs(bowlers) == {}


def test_duplicate_flags_follow_edits_and_removals() -> None:
    bowlers = [
        InputBowler("Alex Bowler", "1234-567890"),
        InputBowler("Other Name", "1234-567890"),
    ]
    original = [
        look_up_bowler(FakeApi([member()], [average()]), bowler)
        for bowler in bowlers
    ]

    flagged = flag_duplicate_results(bowlers, original)

    assert all(result.status is LookupStatus.DUPLICATE_ENTRY for result in flagged)
    assert "multiple names" in flagged[0].note

    remaining = flag_duplicate_results(bowlers[:1], flagged[:1])

    assert remaining[0].status is LookupStatus.NOT_FOUND
    assert remaining[0].note == "Duplicate conflict cleared. Retry this entry to continue."
