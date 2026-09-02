from usbc_average_lookup.app import AverageLookupApp
from usbc_average_lookup.models import LookupResult, LookupStatus


def result(name: str) -> LookupResult:
    return LookupResult(
        input_name=name,
        status=LookupStatus.FOUND,
        average=180,
    )


def test_late_roster_lookup_cannot_replace_newer_results() -> None:
    app = AverageLookupApp.__new__(AverageLookupApp)
    app.lookup_generation = 2
    app.results = [result("New roster")]

    app._lookup_finished(1, [result("Old roster")])

    assert [item.input_name for item in app.results] == ["New roster"]


def test_late_issue_fix_cannot_write_into_replaced_roster() -> None:
    app = AverageLookupApp.__new__(AverageLookupApp)
    app.lookup_generation = 4
    app.bowlers = []
    app.results = []

    app._fix_finished(3, 10, None, result("Old roster"), False)

    assert app.bowlers == []
    assert app.results == []
