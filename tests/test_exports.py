import csv

from usbc_average_lookup.models import LookupResult, LookupStatus
from usbc_average_lookup.services.exports import export_found, export_issues


def read_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.reader(handle))


def test_exports_found_and_issues_separately(tmp_path) -> None:
    results = [
        LookupResult("John Smith", LookupStatus.FOUND, average=187),
        LookupResult("Jane Doe", LookupStatus.NOT_FOUND, note="No matching member"),
    ]
    found_path = tmp_path / "results.csv"
    issues_path = tmp_path / "issues.csv"

    export_found(found_path, results)
    export_issues(issues_path, results)

    assert read_rows(found_path) == [["Name", "Average"], ["John Smith", "187"]]
    assert read_rows(issues_path) == [
        ["Name", "Status", "Notes"],
        ["Jane Doe", "Not found", "No matching member"],
    ]

