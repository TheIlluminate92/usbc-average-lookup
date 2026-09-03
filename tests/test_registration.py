import json
import sqlite3

import pytest

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.services.registration import (
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
    RegistrationTarget,
    RosterRole,
    VerificationState,
)


def test_registration_data_survives_restart(tmp_path) -> None:
    path = tmp_path / "registration.db"
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


def test_register_bowler_many_can_create_different_teams_per_league(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    monday = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    tuesday = store.add_competition("Tuesday", "2026-27", CompetitionKind.LEAGUE)
    tuesday_team = store.add_team(tuesday.id, "Tuesday Crew")

    registrations = store.register_bowler_many(
        "Shared Player",
        "1234-567890",
        [
            RegistrationTarget(monday.id, new_team_name="Monday Crew"),
            RegistrationTarget(tuesday.id, team_id=tuesday_team.id),
        ],
    )

    assert len(registrations) == 2
    assert len(store.bowlers) == 1
    assert store.registration_views(monday.id)[0].team.name == "Monday Crew"
    assert store.registration_views(tuesday.id)[0].team.name == "Tuesday Crew"
    reopened = RegistrationStore(path)
    assert len(reopened.bowlers) == 1
    assert len(reopened.registrations) == 2


def test_register_bowler_many_rolls_back_all_targets_on_error(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.db")
    monday = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    tuesday = store.add_competition("Tuesday", "2026-27", CompetitionKind.LEAGUE)
    store.register_bowler(monday.id, "Already Here", "1234-567890")

    with pytest.raises(RegistrationDataError, match="already registered"):
        store.register_bowler_many(
            "Already Here",
            "1234-567890",
            [
                RegistrationTarget(tuesday.id, new_team_name="Should Roll Back"),
                RegistrationTarget(monday.id),
            ],
        )

    assert len(store.registration_views(monday.id)) == 1
    assert store.registration_views(tuesday.id) == []
    assert not any(team.name == "Should Roll Back" for team in store.teams)


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


def test_reviewed_lookup_reuses_existing_player_identity_and_pool_entry(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    prior = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    other = store.add_competition("Tuesday", "2025-26", CompetitionKind.LEAGUE)
    current = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    pool = store.add_player_pool("2026-27")
    store.set_competition_player_pool(current.id, pool.id)
    known = store.register_bowler(prior.id, "David Brown", "1111-222222")
    store.register_bowler(other.id, "David Brown", "3333-444444")
    pending = store.register_bowler(current.id, "David Brown")
    known_bowler_id = known.bowler_id
    pending_bowler_id = pending.bowler_id

    store.apply_lookup_result(
        pending.id,
        LookupResult(
            input_name="David Brown",
            status=LookupStatus.FOUND,
            membership_id="1111-222222",
            average=181,
            year="2025",
            games=60,
        ),
    )

    view = store.registration_views(current.id)[0]
    assert view.bowler.id == known_bowler_id
    assert view.bowler.membership_id == "1111-222222"
    assert pending_bowler_id not in {item.id for item in store.bowlers}
    assert len(store.bowlers) == 2
    assert {item.id for item in store.pool_bowlers(pool.id)} == {
        known_bowler_id,
    }

    reopened = RegistrationStore(path)
    assert reopened.registration_views(current.id)[0].bowler.id == known_bowler_id
    assert {item.id for item in reopened.pool_bowlers(pool.id)} == {
        known_bowler_id,
    }


def test_reviewed_lookup_rejects_member_already_in_same_competition(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    competition = store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)
    store.register_bowler(competition.id, "David Brown", "1111-222222")
    other = store.register_bowler(
        competition.id, "David Brown", "3333-444444"
    )
    original_bowler_id = other.bowler_id

    with pytest.raises(RegistrationDataError, match="already registered"):
        store.apply_lookup_result(
            other.id,
            LookupResult(
                input_name="David Brown",
                status=LookupStatus.FOUND,
                membership_id="1111-222222",
                average=181,
            ),
        )

    view = next(
        item
        for item in store.registration_views(competition.id)
        if item.registration.id == other.id
    )
    assert view.bowler.id == original_bowler_id
    assert view.bowler.membership_id == "3333-444444"
    assert view.registration.verification is VerificationState.NOT_CHECKED

    reopened = RegistrationStore(path)
    reopened_view = next(
        item
        for item in reopened.registration_views(competition.id)
        if item.registration.id == other.id
    )
    assert reopened_view.bowler.id == original_bowler_id
    assert reopened_view.bowler.membership_id == "3333-444444"


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


def test_correcting_to_existing_identity_adds_player_to_linked_pool(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.db")
    prior = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    other = store.add_competition("Tuesday", "2026-27", CompetitionKind.LEAGUE)
    current = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    pool = store.add_player_pool("2026-27")
    store.set_competition_player_pool(current.id, pool.id)
    target = store.register_bowler(prior.id, "Correct Player", "1111-222222")
    typo = store.register_bowler(current.id, "Correct Player", "3333-444444")
    store.register_existing_bowler(other.id, typo.bowler_id)

    store.update_registration(
        typo.id, "Correct Player", "1111-222222", ""
    )

    assert store.registration_views(current.id)[0].bowler.id == target.bowler_id
    assert target.bowler_id in {item.id for item in store.pool_bowlers(pool.id)}


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


def test_lookup_roster_can_be_imported_into_permanent_player_list(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    existing = store.register_bowler(
        competition.id, "David Brown", "1111-222222"
    )

    added, reused = store.import_players(
        [
            InputBowler("David Brown", "1111-222222"),
            InputBowler("New Player", "3333-444444"),
            InputBowler("Needs Review"),
            InputBowler("Needs Review"),
        ]
    )

    assert added == 3
    assert reused == 1
    assert len(store.bowlers) == 4
    assert store.registration_views(competition.id)[0].bowler.id == existing.bowler_id
    added_again, reused_again = store.import_players(
        [
            InputBowler("David Brown", "1111-222222"),
            InputBowler("New Player", "3333-444444"),
            InputBowler("Needs Review"),
            InputBowler("Needs Review"),
        ]
    )
    assert added_again == 0
    assert reused_again == 4
    reopened = RegistrationStore(path)
    assert [item.name for item in reopened.bowlers].count("Needs Review") == 2
    assert ("David Brown", "1111-222222") in {
        (item.name, item.membership_id) for item in reopened.bowlers
    }
    assert ("New Player", "3333-444444") in {
        (item.name, item.membership_id) for item in reopened.bowlers
    }


def test_copy_team_carries_active_roster_into_new_league_without_averages(
    tmp_path,
) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    old = store.add_competition("Monday", "2025-26", CompetitionKind.LEAGUE)
    new = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    pool = store.add_player_pool("2026-27")
    store.set_competition_player_pool(new.id, pool.id)
    old_team = store.add_team(old.id, "Pin Pals")
    other_new_team = store.add_team(new.id, "Already Assigned")
    regular = store.register_bowler(
        old.id, "Regular Player", "1111-111111", old_team.id
    )
    store.register_bowler(
        old.id,
        "Sub Player",
        "2222-222222",
        old_team.id,
        RosterRole.SUBSTITUTE,
    )
    withdrawn = store.register_bowler(
        old.id, "Former Player", "3333-333333", old_team.id
    )
    assigned_elsewhere = store.register_bowler(
        old.id, "Busy Player", "4444-444444", old_team.id
    )
    store.set_withdrawn(withdrawn.id, True)
    store.register_existing_bowler(new.id, regular.bowler_id)
    store.register_existing_bowler(
        new.id, assigned_elsewhere.bowler_id, other_new_team.id
    )

    copied_team, copied, skipped = store.copy_team_to_competition(
        old_team.id, new.id, "Pin Pals", copy_roster=True
    )

    assert copied == 2
    assert skipped == 1
    assert [item.name for item in store.list_teams(old.id)] == ["Pin Pals"]
    assert {item.name for item in store.list_teams(new.id)} == {
        "Already Assigned",
        "Pin Pals",
    }
    new_views = {item.bowler.name: item for item in store.registration_views(new.id)}
    assert new_views["Regular Player"].team.id == copied_team.id
    assert new_views["Regular Player"].registration.average is None
    assert (
        new_views["Regular Player"].registration.verification
        is VerificationState.NOT_CHECKED
    )
    assert new_views["Sub Player"].team.id == copied_team.id
    assert (
        new_views["Sub Player"].registration.roster_role
        is RosterRole.SUBSTITUTE
    )
    assert new_views["Busy Player"].team.id == other_new_team.id
    assert "Former Player" not in new_views
    assert {item.name for item in store.pool_bowlers(pool.id)} == {
        "Busy Player",
        "Regular Player",
        "Sub Player",
    }

    reopened = RegistrationStore(path)
    reopened_views = {
        item.bowler.name: item for item in reopened.registration_views(new.id)
    }
    assert reopened_views["Regular Player"].team.name == "Pin Pals"
    assert reopened_views["Sub Player"].team.name == "Pin Pals"


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
    path = tmp_path / "registration.db"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(RegistrationDataError, match="could not be read"):
        RegistrationStore(path)

    assert path.read_text(encoding="utf-8") == "not json"


def test_player_pools_and_roster_roles_survive_database_restart(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    pool = store.add_player_pool("2026-27")
    competition = store.add_competition("Monday", "2026-27", CompetitionKind.LEAGUE)
    store.set_competition_player_pool(competition.id, pool.id)
    team = store.add_team(competition.id, "Pin Pals")
    regular = store.register_bowler(
        competition.id, "Regular Player", "1111-111111", team.id
    )
    substitute = store.register_bowler(
        competition.id,
        "Sub Player",
        "2222-222222",
        roster_role=RosterRole.SUBSTITUTE,
    )
    store.set_withdrawn(regular.id, True)

    reopened = RegistrationStore(path)
    views = {
        view.bowler.name: view for view in reopened.registration_views(competition.id)
    }

    assert reopened.competitions[0].player_pool_id == pool.id
    assert {item.name for item in reopened.pool_bowlers(pool.id)} == {
        "Regular Player",
        "Sub Player",
    }
    assert views["Regular Player"].registration.withdrawn
    assert views["Sub Player"].registration.id == substitute.id
    assert views["Sub Player"].registration.roster_role is RosterRole.SUBSTITUTE
    assert views["Sub Player"].team is None


def test_database_round_trip_handles_200_bowlers(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    competition = store.add_competition("Large League", "2026-27", CompetitionKind.LEAGUE)
    bowlers = [
        InputBowler(f"Player {number:03}", f"{1000 + number:04}-{200000 + number:06}")
        for number in range(200)
    ]

    store.register_team(competition.id, "All Bowlers", bowlers)
    reopened = RegistrationStore(path)

    assert len(reopened.bowlers) == 200
    assert len(reopened.registration_views(competition.id)) == 200


def test_registration_database_is_versioned_sqlite(tmp_path) -> None:
    path = tmp_path / "registration.db"
    store = RegistrationStore(path)
    store.add_competition("Open", "2027", CompetitionKind.TOURNAMENT)

    assert path.read_bytes().startswith(b"SQLite format 3\x00")
    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        competition = connection.execute(
            "SELECT name, season, kind FROM competitions"
        ).fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

        assert version == 4
    assert competition == ("Open", "2027", "Tournament")
    assert integrity == "ok"


@pytest.mark.parametrize("schema_version", [1, 2])
def test_legacy_json_migrates_to_sqlite_with_backup(
    tmp_path, schema_version: int
) -> None:
    legacy_path = tmp_path / "registration-data.json"
    database_path = tmp_path / "bowling-manager.db"
    competition = {
        "id": "competition-1",
        "name": "Monday Misfits",
        "season": "2025-26",
        "kind": "League",
        "created_at": "2025-08-01T00:00:00+00:00",
        "archived": False,
    }
    registration = {
        "id": "registration-1",
        "competition_id": "competition-1",
        "bowler_id": "bowler-1",
        "team_id": "team-1",
        "verification": "Not checked",
        "average": None,
        "average_year": "",
        "games": None,
        "note": "",
        "withdrawn": False,
        "created_at": "2025-08-01T00:00:00+00:00",
    }
    document = {
        "schemaVersion": schema_version,
        "competitions": [competition],
        "bowlers": [
            {"id": "bowler-1", "name": "Player One", "membership_id": "1234-567890"}
        ],
        "teams": [
            {"id": "team-1", "competition_id": "competition-1", "name": "Pin Pals"}
        ],
        "registrations": [registration],
    }
    if schema_version == 2:
        competition["player_pool_id"] = "pool-1"
        registration["roster_role"] = "Substitute"
        document["playerPools"] = [
            {
                "id": "pool-1",
                "label": "2025-26",
                "created_at": "2025-08-01T00:00:00+00:00",
                "archived": False,
            }
        ]
        document["playerPoolEntries"] = [
            {"pool_id": "pool-1", "bowler_id": "bowler-1"}
        ]
    original_text = json.dumps(document, indent=2)
    legacy_path.write_text(original_text, encoding="utf-8")

    migrated = RegistrationStore(database_path, legacy_json_path=legacy_path)

    backup_path = tmp_path / "registration-data.pre-sqlite-backup.json"
    assert database_path.read_bytes().startswith(b"SQLite format 3\x00")
    assert legacy_path.read_text(encoding="utf-8") == original_text
    assert backup_path.read_text(encoding="utf-8") == original_text
    assert migrated.registration_views("competition-1")[0].team.name == "Pin Pals"
    if schema_version == 2:
        assert migrated.registrations[0].roster_role is RosterRole.SUBSTITUTE
        assert migrated.pool_bowlers("pool-1")[0].name == "Player One"
    else:
        assert migrated.registrations[0].roster_role is RosterRole.REGULAR


def test_invalid_legacy_json_does_not_create_database_or_change_source(tmp_path) -> None:
    legacy_path = tmp_path / "registration-data.json"
    database_path = tmp_path / "bowling-manager.db"
    legacy_path.write_text("not json", encoding="utf-8")

    with pytest.raises(RegistrationDataError, match="could not be read"):
        RegistrationStore(database_path, legacy_json_path=legacy_path)

    assert legacy_path.read_text(encoding="utf-8") == "not json"
    assert not database_path.exists()


def test_default_store_discovers_and_migrates_legacy_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data_folder = tmp_path / "Bowling Manager"
    data_folder.mkdir()
    legacy_path = data_folder / "registration-data.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "competitions": [],
                "bowlers": [],
                "playerPools": [],
                "playerPoolEntries": [],
                "teams": [],
                "registrations": [],
            }
        ),
        encoding="utf-8",
    )

    store = RegistrationStore()

    assert store.path == data_folder / "bowling-manager.db"
    assert store.path.read_bytes().startswith(b"SQLite format 3\x00")
    assert (data_folder / "registration-data.pre-sqlite-backup.json").exists()


def test_store_change_listener_runs_after_successful_save(tmp_path) -> None:
    store = RegistrationStore(tmp_path / "registration.db")
    notifications: list[str] = []
    unsubscribe = store.add_change_listener(lambda: notifications.append("saved"))

    store.add_competition("Monday Misfits", "2026-27", CompetitionKind.LEAGUE)
    unsubscribe()
    store.add_competition("Tuesday Twisters", "2026-27", CompetitionKind.LEAGUE)

    assert notifications == ["saved"]
