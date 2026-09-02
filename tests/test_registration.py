import json

import pytest

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.services.registration import (
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
    RosterRole,
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


def test_failed_duplicate_registration_does_not_change_player_identity(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    store.register_bowler(competition.id, "David Brown")

    with pytest.raises(RegistrationDataError, match="already registered"):
        store.register_bowler(competition.id, "David Brown", "1111-222222")

    assert store.bowlers[0].membership_id == ""


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


def test_player_management_edit_updates_history_and_invalidates_averages(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    old = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    new = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    first = store.register_bowler(old.id, "Erik Bowler", "1234-567890")
    store.register_bowler(new.id, "Erik Bowler", "1234-567890")
    store.apply_lookup_result(
        first.id,
        LookupResult(
            input_name="Erik Bowler",
            status=LookupStatus.FOUND,
            membership_id="1234-567890",
            average=180,
        ),
    )

    store.update_bowler_profile(store.bowlers[0].id, "Erik B.", "1234-567890")

    assert store.bowlers[0].name == "Erik B."
    assert all(item.average is None for item in store.registrations)
    assert all(
        item.verification is VerificationState.NOT_CHECKED
        for item in store.registrations
    )


def test_team_and_competition_management_changes_persist(tmp_path) -> None:
    path = tmp_path / "registration.json"
    store = RegistrationStore(path)
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    team = store.add_team(competition.id, "Old Name")

    store.rename_team(team.id, "New Name")
    store.update_competition(
        competition.id, "Monday Misfits", "2026-27", CompetitionKind.LEAGUE
    )
    store.set_competition_archived(competition.id, True)

    reopened = RegistrationStore(path)
    assert reopened.teams[0].name == "New Name"
    assert reopened.competitions[0].name == "Monday Misfits"
    assert reopened.competitions[0].archived


def test_player_management_rejects_duplicate_member_id(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    store.register_bowler(competition.id, "First Player", "1111-222222")
    store.register_bowler(competition.id, "Second Player", "3333-444444")

    with pytest.raises(RegistrationDataError, match="another player"):
        store.update_bowler_profile(
            store.bowlers[1].id, "Second Player", "1111-222222"
        )


def test_substitute_can_be_league_wide_or_assigned_to_team(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    team = store.add_team(competition.id, "Team One")
    registration = store.register_bowler(
        competition.id,
        "Sub Player",
        "1234-567890",
        roster_role=RosterRole.SUBSTITUTE,
    )

    view = store.registration_views(competition.id)[0]
    assert view.team is None
    assert view.registration.roster_role is RosterRole.SUBSTITUTE
    assert view.status == "Not checked"

    store.assign_registration(
        registration.id, team.id, RosterRole.SUBSTITUTE
    )

    assigned = store.registration_views(competition.id)[0]
    assert assigned.team.name == "Team One"
    assert assigned.registration.roster_role is RosterRole.SUBSTITUTE


def test_removing_player_from_team_keeps_league_registration(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    team = store.add_team(competition.id, "Team One")
    registration = store.register_bowler(
        competition.id, "Regular Player", team_id=team.id
    )

    store.assign_registration(registration.id, "", RosterRole.REGULAR)

    view = store.registration_views(competition.id)[0]
    assert view.team is None
    assert view.status == "Unassigned team"
    assert len(store.registrations) == 1


def test_yearly_player_pool_can_be_copied_without_changing_prior_year(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    player = store.register_bowler(competition.id, "Player One")
    old_pool = store.add_player_pool("2025-26")
    store.add_bowler_to_pool(old_pool.id, player.bowler_id)

    new_pool = store.copy_player_pool(old_pool.id, "2026-27")
    store.remove_bowler_from_pool(new_pool.id, player.bowler_id)

    assert [item.name for item in store.pool_bowlers(old_pool.id)] == ["Player One"]
    assert store.pool_bowlers(new_pool.id) == []


def test_linked_competition_automatically_adds_registrations_to_pool(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    pool = store.add_player_pool("2026-27")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    store.set_competition_player_pool(competition.id, pool.id)

    registration = store.register_bowler(competition.id, "Player One")

    assert [item.id for item in store.pool_bowlers(pool.id)] == [
        registration.bowler_id
    ]


def test_linking_pool_includes_players_already_registered_for_season(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.json")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    registration = store.register_bowler(competition.id, "Player One")
    pool = store.add_player_pool("2026-27")

    store.set_competition_player_pool(competition.id, pool.id)

    assert [item.id for item in store.pool_bowlers(pool.id)] == [
        registration.bowler_id
    ]


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

    assert document["schemaVersion"] == 2
    assert document["competitions"][0]["kind"] == "Tournament"


def test_version_one_registration_data_migrates_on_next_save(tmp_path) -> None:
    path = tmp_path / "registration.json"
    store = RegistrationStore(path)
    competition = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    store.register_bowler(competition.id, "Player One")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schemaVersion"] = 1
    document.pop("playerPools")
    document.pop("playerPoolEntries")
    for item in document["competitions"]:
        item.pop("player_pool_id")
    for item in document["registrations"]:
        item.pop("roster_role")
    path.write_text(json.dumps(document), encoding="utf-8")

    migrated = RegistrationStore(path)
    migrated.save()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schemaVersion"] == 2
    assert migrated.registrations[0].roster_role is RosterRole.REGULAR
