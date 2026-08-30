from usbc_average_lookup.models import CompositeAverage, InputBowler, LookupStatus, Member
from usbc_average_lookup.services.lookup import look_up_bowler


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


def test_returns_not_found() -> None:
    result = look_up_bowler(FakeApi(), InputBowler("Missing Bowler"))

    assert result.status is LookupStatus.NOT_FOUND


def test_returns_multiple_matches() -> None:
    result = look_up_bowler(
        FakeApi([member(), member(suffix="999999")]), InputBowler("Alex Bowler")
    )

    assert result.status is LookupStatus.MULTIPLE_MATCHES


def test_returns_inactive_member() -> None:
    result = look_up_bowler(
        FakeApi([member(active=False)]), InputBowler("Former Bowler")
    )

    assert result.status is LookupStatus.INACTIVE_MEMBER


def test_returns_no_average() -> None:
    result = look_up_bowler(FakeApi([member()]), InputBowler("Alex Bowler"))

    assert result.status is LookupStatus.NO_AVERAGE
