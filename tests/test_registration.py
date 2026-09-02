import json

import pytest

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.services.registration import (
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
    VerificationState,
)


def test_registration_data_survives_restart(tmp_path) -> None:
    path = tmp_path / "registration.json"
    store = RegistrationStore(path)
    competition = store.add_competition(
        "Monday Misfits", "2026-27", CompetitionKind.LEAGUE
    )
    team = store.add_team(competition.id, "Split Happens")
    registration = store.register_bowler(
        competition.id, "Erik Bowler", "1234-567890", team.id
    )

    reopened = RegistrationStore(path)
    views = reopened.registration_views(competition.id)

    assert len(views) == 1
    assert views[0].registration.id == registration.id
    assert views[0].bowler.membership_id == "1234-567890"
    assert views[0].team.name == "Split Happens"
    assert views[0].status == "Not checked"


def test_same_bowler_can_join_multiple_seasons_with_different_teams(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    old = store.add_competition("Monday Misfits", "2025-26", CompetitionKind.LEAGUE)
    new = store.add_competition("Monday Misfits", "2026-27", CompetitionKind.LEAGUE)
    old_team = store.add_team(old.id, "Old Team")
    new_team = store.add_team(new.id, "New Team")

    store.register_bowler(old.id, "Erik Bowler", "1234-567890", old_team.id)
    store.register_bowler(new.id, "Erik Bowler", "1234-567890", new_team.id)

    assert len(store.bowlers) == 1
    assert store.registration_views(old.id)[0].team.name == "Old Team"
    assert store.registration_views(new.id)[0].team.name == "New Team"


def test_duplicate_registration_is_rejected(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Tuesday Twisters", "2026-27", CompetitionKind.LEAGUE)
    store.register_bowler(competition.id, "David Brown", "1111-222222")

    with pytest.raises(RegistrationDataError, match="already registered"):
        store.register_bowler(competition.id, "David Brown", "1111-222222")


def test_different_member_ids_keep_same_named_bowlers_separate(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)

    store.register_bowler(competition.id, "David Brown", "1111-222222")
    store.register_bowler(competition.id, "David Brown", "3333-444444")

    assert len(store.bowlers) == 2
    assert len(store.registration_views(competition.id)) == 2


def test_team_registration_is_atomic_when_a_bowler_is_duplicate(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    store.register_bowler(competition.id, "Already Here", "1111-222222")

    with pytest.raises(RegistrationDataError, match="already registered"):
        store.register_team(
            competition.id,
            "Team Trouble",
            [
                InputBowler("New Bowler", "2222-333333"),
                InputBowler("Already Here", "1111-222222"),
            ],
        )

    assert len(store.registration_views(competition.id)) == 1
    assert not any(team.name == "Team Trouble" for team in store.teams)


def test_lookup_result_updates_registration_without_replacing_raw_score(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    team = store.add_team(competition.id, "Team One")
    registration = store.register_bowler(competition.id, "Erik Bowler", team_id=team.id)

    store.apply_lookup_result(
        registration.id,
        LookupResult(
            input_name="Erik Bowler",
            status=LookupStatus.FOUND,
            membership_id="1234-567890",
            average=187,
            year="2026",
            games=72,
            note="2026 standard composite, 72 games",
        ),
    )

    view = store.registration_views(competition.id)[0]
    assert view.registration.verification is VerificationState.VERIFIED
    assert view.registration.average == 187
    assert view.bowler.membership_id == "1234-567890"
    assert view.status == "Ready"


def test_interrupted_check_resets_to_not_checked_on_restart(tmp_path) -> None:
    path = tmp_path / "registration.json"
    store = RegistrationStore(path)
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    registration = store.register_bowler(competition.id, "Erik Bowler")
    store.mark_checking(registration.id)

    reopened = RegistrationStore(path)

    assert reopened.registrations[0].verification is VerificationState.NOT_CHECKED


def test_member_without_average_has_specific_review_status(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    team = store.add_team(competition.id, "Team One")
    registration = store.register_bowler(competition.id, "New Bowler", team_id=team.id)

    store.apply_lookup_result(
        registration.id,
        LookupResult(
            input_name="New Bowler",
            status=LookupStatus.NO_AVERAGE,
            membership_id="1234-567890",
            note="Member found, but no standard composite average is available",
        ),
    )

    view = store.registration_views(competition.id)[0]
    assert view.registration.verification is VerificationState.NO_AVERAGE
    assert view.status == "No average available"


def test_correcting_identity_clears_stale_average_and_moves_team(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    old_team = store.add_team(competition.id, "Old Team")
    new_team = store.add_team(competition.id, "New Team")
    registration = store.register_bowler(
        competition.id, "Wrong Name", "1111-222222", old_team.id
    )
    store.apply_lookup_result(
        registration.id,
        LookupResult(
            input_name="Wrong Name",
            status=LookupStatus.FOUND,
            membership_id="1111-222222",
            average=180,
        ),
    )

    store.update_registration(
        registration.id, "Correct Name", "3333-444444", new_team.id
    )

    view = store.registration_views(competition.id)[0]
    assert view.bowler.name == "Correct Name"
    assert view.bowler.membership_id == "3333-444444"
    assert view.team.name == "New Team"
    assert view.registration.average is None
    assert view.registration.verification is VerificationState.NOT_CHECKED


def test_correcting_member_id_can_reuse_existing_identity(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    old = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    new = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    store.register_bowler(old.id, "Erik Bowler", "1234-567890")
    typo = store.register_bowler(new.id, "Erik Bowler", "1234-567899")

    store.update_registration(typo.id, "Erik Bowler", "1234-567890", "")

    assert len(store.bowlers) == 1
    assert store.registration_views(new.id)[0].bowler.membership_id == "1234-567890"


def test_invalid_file_is_not_silently_overwritten(tmp_path) -> None:
    path = tmp_path / "registration.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(RegistrationDataError, match="could not be read"):
        RegistrationStore(path)

    assert path.read_text(encoding="utf-8") == "not json"


def test_json_uses_versioned_plain_data(tmp_path) -> None:
    path = tmp_path / "registration.json"
    store = RegistrationStore(path)
    store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)

    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["schemaVersion"] == 1
    assert document["competitions"][0]["kind"] == "Tournament"
