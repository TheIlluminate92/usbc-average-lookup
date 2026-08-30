import json

from usbc_average_lookup.models import LookupResult, LookupStatus
from usbc_average_lookup.services.exports import export_json


def test_json_export_keeps_every_bowler_and_optional_id(tmp_path) -> None:
    results = [
        LookupResult("Alex Bowler", LookupStatus.FOUND, "1234-567890", average=187),
        LookupResult("Jamie Bowler", LookupStatus.NOT_FOUND, note="Check the spelling"),
    ]
    path = tmp_path / "averages.json"

    export_json(path, results)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == 1
    assert document["summary"]["processed"] == 2
    assert document["bowlers"] == [
        {
            "name": "Alex Bowler",
            "membershipId": "1234-567890",
            "average": 187,
            "status": "Found",
            "notes": None,
        },
        {
            "name": "Jamie Bowler",
            "membershipId": None,
            "average": None,
            "status": "Not found",
            "notes": "Check the spelling",
        },
    ]
