import csv
import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from usbc_average_lookup.models import LookupResult, LookupStatus


def export_found(path: Path, results: Iterable[LookupResult]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Average"])
        writer.writerows(
            (result.input_name, result.average)
            for result in results
            if result.status is LookupStatus.FOUND
        )


def export_issues(path: Path, results: Iterable[LookupResult]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Status", "Notes"])
        writer.writerows(
            (result.input_name, result.status.value, result.note)
            for result in results
            if result.status is not LookupStatus.FOUND
        )


def export_json(path: Path, results: Iterable[LookupResult]) -> None:
    result_list = list(results)
    counts = Counter(result.status for result in result_list)
    document = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": {
            "processed": len(result_list),
            **{status.name.lower(): counts[status] for status in LookupStatus},
        },
        "bowlers": [
            {
                "name": result.input_name,
                "membershipId": result.membership_id or None,
                "average": result.average,
                "status": result.status.value,
                "notes": result.note or None,
            }
            for result in result_list
        ],
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
