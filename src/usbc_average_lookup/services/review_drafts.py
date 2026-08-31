from __future__ import annotations

import json
from pathlib import Path

from usbc_average_lookup.models import (
    AverageCondition,
    AverageOption,
    AverageSource,
    LookupResult,
    LookupStatus,
    Member,
)


def load_review_draft(path: Path) -> list[LookupResult] | None:
    """Restore a structured Average Assistant draft, or return None for roster JSON."""

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or "schemaVersion" not in payload:
        return None
    records = payload.get("bowlers")
    if not isinstance(records, list) or not all(
        isinstance(record, dict) and "status" in record for record in records
    ):
        return None
    try:
        schema_version = int(payload["schemaVersion"])
    except (TypeError, ValueError) as error:
        raise ValueError("The review draft has an invalid schema version") from error
    if schema_version < 3 or schema_version > 4:
        raise ValueError(
            f"Review draft version {schema_version} is not supported by this app"
        )
    return [
        _result_from_document(record, position, schema_version)
        for position, record in enumerate(records, start=1)
    ]


def _result_from_document(
    record: dict[str, object], position: int, schema_version: int
) -> LookupResult:
    try:
        name = _required_text(record, "name")
        membership_id = _text(record.get("membershipId"))
        status = LookupStatus(_required_text(record, "status"))
        options_document = record.get("availableAverages", [])
        if not isinstance(options_document, list):
            raise ValueError("availableAverages must be a list")
        options = tuple(
            _option_from_document(option, index)
            for index, option in enumerate(options_document, start=1)
        )
        selected_document = record.get("selectedAverage")
        selected_key = (
            _text(selected_document.get("id"))
            if isinstance(selected_document, dict)
            else ""
        )
        member_document = record.get("member")
        member = (
            _member_from_document(member_document)
            if isinstance(member_document, dict)
            else _legacy_member(record, name, membership_id)
        )
        candidates_document = record.get("candidates", [])
        candidates = (
            tuple(
                _member_from_document(candidate)
                for candidate in candidates_document
                if isinstance(candidate, dict)
            )
            if schema_version >= 4 and isinstance(candidates_document, list)
            else ()
        )
        return LookupResult(
            input_name=name,
            status=status,
            membership_id=membership_id,
            average=_optional_int(record.get("average")),
            year=_text(record.get("year")),
            games=_optional_int(record.get("games")),
            note=_text(record.get("notes")),
            member=member,
            candidates=candidates,
            confirmed_inactive=bool(
                record.get("confirmedInactive")
                or (
                    status is LookupStatus.INACTIVE_MEMBER
                    and record.get("reviewed") is True
                )
            ),
            available_averages=options,
            selected_average_key=selected_key,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Review draft bowler {position} is invalid: {error}") from error


def _option_from_document(record: object, position: int) -> AverageOption:
    if not isinstance(record, dict):
        raise ValueError(f"average choice {position} must be an object")
    return AverageOption(
        key=_required_text(record, "id"),
        average=_required_int(record, "average"),
        games=_optional_int(record.get("games")),
        season=_text(record.get("season")),
        source=AverageSource(_required_text(record, "source")),
        condition=AverageCondition(_required_text(record, "condition")),
        league=_text(record.get("league")),
        center=_text(record.get("center")),
        association=_text(record.get("association")),
        original_average=_optional_int(record.get("originalAverage")),
        tournament=_text(record.get("tournament")),
        adjusted_by=_text(record.get("adjustedBy")),
        adjusted_date=_text(record.get("adjustedDate")),
        hand=_text(record.get("hand")),
    )


def _member_from_document(record: dict[str, object]) -> Member:
    return Member(
        member_id=_required_text(record, "memberId"),
        prefix=_required_text(record, "prefix"),
        suffix=_required_text(record, "suffix"),
        first_name=_text(record.get("firstName")),
        last_name=_text(record.get("lastName")),
        active=bool(record.get("active")),
        association=_text(record.get("association")),
        association_state=_text(record.get("associationState")),
    )


def _legacy_member(
    record: dict[str, object], name: str, membership_id: str
) -> Member | None:
    active = record.get("active")
    if active is None or "-" not in membership_id:
        return None
    prefix, suffix = membership_id.split("-", 1)
    first_name, _, last_name = name.partition(" ")
    return Member(
        member_id=membership_id,
        prefix=prefix,
        suffix=suffix,
        first_name=first_name,
        last_name=last_name,
        active=bool(active),
        association=_text(record.get("association")),
        association_state=_text(record.get("associationState")),
    )


def _required_text(record: dict[str, object], key: str) -> str:
    value = _text(record.get(key))
    if not value:
        raise ValueError(f"{key} is missing")
    return value


def _required_int(record: dict[str, object], key: str) -> int:
    value = _optional_int(record.get(key))
    if value is None:
        raise ValueError(f"{key} is missing")
    return value


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()
