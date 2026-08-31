import json

import pytest

from usbc_average_lookup.models import (
    AverageCondition,
    AverageOption,
    AverageSource,
    LookupResult,
    LookupStatus,
    Member,
)
from usbc_average_lookup.services.exports import export_json
from usbc_average_lookup.services.review_drafts import load_review_draft


def test_round_trips_complete_review_state(tmp_path) -> None:
    member = Member(
        member_id="1234-567890",
        prefix="1234",
        suffix="567890",
        first_name="Alex",
        last_name="Bowler",
        active=True,
        association="Example USBC",
        association_state="TX",
    )
    candidate = Member(
        member_id="4321-98765",
        prefix="4321",
        suffix="98765",
        first_name="Alex",
        last_name="Bowler",
        active=False,
    )
    choice = AverageOption(
        key="league-1",
        average=187,
        games=48,
        season="2025",
        source=AverageSource.LEAGUE,
        condition=AverageCondition.STANDARD,
        league="Tuesday Twisters",
        center="Example Lanes",
    )
    original = [
        LookupResult(
            input_name="Alex Bowler",
            status=LookupStatus.REVIEW_REQUIRED,
            membership_id=member.member_id,
            average=choice.average,
            year=choice.season,
            games=choice.games,
            note="Choose the tournament average",
            member=member,
            candidates=(candidate,),
            available_averages=(choice,),
            selected_average_key=choice.key,
        )
    ]
    path = tmp_path / "review-draft.json"

    export_json(path, original)

    assert load_review_draft(path) == original


def test_plain_roster_json_is_not_treated_as_a_review_draft(tmp_path) -> None:
    path = tmp_path / "roster.json"
    path.write_text(json.dumps({"bowlers": [{"name": "Alex Bowler"}]}))

    assert load_review_draft(path) is None


def test_rejects_newer_review_draft_schema(tmp_path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schemaVersion": 99, "bowlers": []}))

    with pytest.raises(ValueError, match="not supported"):
        load_review_draft(path)


def test_restores_legacy_schema_three_review_draft(tmp_path) -> None:
    path = tmp_path / "legacy-review.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 3,
                "bowlers": [
                    {
                        "name": "Alex Bowler",
                        "membershipId": "1234-567890",
                        "average": 187,
                        "year": "2025",
                        "games": 48,
                        "reviewed": False,
                        "status": "Review required",
                        "notes": None,
                        "active": True,
                        "association": "Example USBC",
                        "associationState": "TX",
                        "selectedAverage": {
                            "id": "composite-2025",
                            "average": 187,
                            "games": 48,
                            "season": "2025",
                            "source": "Composite",
                            "condition": "Standard",
                        },
                        "availableAverages": [
                            {
                                "id": "composite-2025",
                                "average": 187,
                                "games": 48,
                                "season": "2025",
                                "source": "Composite",
                                "condition": "Standard",
                            }
                        ],
                    }
                ],
            }
        )
    )

    restored = load_review_draft(path)

    assert restored is not None
    assert restored[0].status is LookupStatus.REVIEW_REQUIRED
    assert restored[0].member is not None
    assert restored[0].member.member_id == "1234-567890"
    assert restored[0].selected_average_key == "composite-2025"
