import json
import sqlite3
from dataclasses import replace

import pytest

from usbc_average_lookup.database import MIGRATIONS, BowlerDatabase
from usbc_average_lookup.models import CompositeAverage, InputBowler, Member


@pytest.fixture
def db(tmp_path):
    return BowlerDatabase(tmp_path / "bowlers.sqlite3")


@pytest.fixture
def member():
    return Member(
        "101",
        "1234",
        "567890",
        "Alex",
        "Bowler",
        True,
        middle_initial="Q",
        gender="M",
        flags={"stringpin": True},
    )


def seed(db, member):
    bowler_id = db.import_bowlers([InputBowler("Alex Bowler", "1234-567890")]).added[0]
    average = CompositeAverage("2025", 60, 180, False, False, "R")
    db.save_refresh(bowler_id, member, [average], {"members/id": {"data": "value"}})
    return bowler_id, average


def test_persists_reopens_and_reuses_id(db, member):
    bowler_id, _ = seed(db, member)
    reopened = BowlerDatabase(db.path)
    result = reopened.import_bowlers([InputBowler("Changed name", "1234-567890")])
    assert result.reused == (bowler_id,)
    assert not result.added
    assert reopened.get(bowler_id)["gender"] == "M"
    assert len(reopened.averages(bowler_id)) == 1


def test_revisions_and_absent_years_are_retained(db, member):
    bowler_id, average = seed(db, member)
    newer = replace(average, year="2026", average=190)
    db.save_refresh(bowler_id, member, [average, newer], {})
    db.save_refresh(bowler_id, member, [replace(newer, games=72, average=191)], {})
    assert len(db.averages(bowler_id)) == 2
    assert [r["average"] for r in db.averages(bowler_id, history=True)] == [191, 190, 180]
    db.save_refresh(bowler_id, member, [], {})
    assert len(db.averages(bowler_id)) == 2


def test_idempotent_refresh_and_snapshot_versioning(db, member):
    bowler_id, average = seed(db, member)
    db.save_refresh(bowler_id, member, [average], {"members/id": {"data": "value"}})
    assert len(db.averages(bowler_id, history=True)) == 1
    assert len(db.snapshots(bowler_id)) == 1
    db.save_refresh(bowler_id, member, [average], {"members/id": {"data": "changed"}})
    assert len(db.snapshots(bowler_id)) == 2


def test_all_types_and_hands_stay_distinct(db, member):
    bowler_id, average = seed(db, member)
    db.save_refresh(
        bowler_id,
        member,
        [
            replace(average, sport=True),
            replace(average, challenge=True),
            replace(average, hand="L"),
        ],
        {},
    )
    assert len(db.averages(bowler_id)) == 4


def test_snapshot_and_normalized_fields_strip_nested_credentials(db, member):
    bowler_id, average = seed(db, member)
    raw = {
        "Authorization": "secret1",
        "nested": [{"access_token": "secret2", "safe": 7}],
        "message": "Bearer secret3",
        "cookie": "secret4",
        "extra": "useful",
    }
    db.save_refresh(bowler_id, replace(member, raw=raw), [replace(average, raw=raw)], {"api": raw})
    with db.connect() as connection:
        dump = "\n".join(connection.iterdump())
    assert "secret" not in dump
    assert "useful" in dump
    assert json.loads(db.get(bowler_id)["member_json"])["raw"]["nested"] == [{"safe": 7}]


def test_failed_refresh_does_not_destroy_previous_data(db, member):
    bowler_id, _ = seed(db, member)
    before = db.get(bowler_id)["refreshed_at"]
    db.save_status(bowler_id, "Refresh failed", "offline")
    assert db.get(bowler_id)["refreshed_at"] == before
    assert db.averages(bowler_id)[0]["average"] == 180


def test_same_name_different_ids_and_unresolved_names(db):
    imported = db.import_bowlers(
        [InputBowler("Alex Bowler", "1234-1"), InputBowler("Alex Bowler", "1234-2")]
    )
    assert len(imported.added) == 2
    conflict = db.import_bowlers([InputBowler("  ALEX   BOWLER ")])
    assert len(conflict.conflicts) == 1
    assert len(db.list_bowlers()) == 2
    assert len(db.import_bowlers([InputBowler("New Bowler"), InputBowler("new bowler")]).added) == 1


def test_import_validates_all_rows_before_changes(db):
    with pytest.raises(ValueError):
        db.import_bowlers([InputBowler("Good Bowler"), InputBowler("Bad Bowler", "not-an-id")])
    assert db.list_bowlers() == []


def test_resolved_duplicate_reuses_canonical_and_keeps_history(db, member):
    canonical, average = seed(db, member)
    unresolved = db.import_bowlers([InputBowler("Alex Q Bowler")]).added[0]
    actual = db.save_refresh(unresolved, member, [replace(average, year="2026")], {})
    assert actual == canonical
    assert len(db.list_bowlers()) == 1
    assert len(db.averages(canonical)) == 2


def test_wrong_member_id_does_not_overwrite(db, member):
    bowler_id, average = seed(db, member)
    with pytest.raises(ValueError, match="different USBC ID"):
        db.save_refresh(bowler_id, replace(member, suffix="999"), [average], {})
    assert db.get(bowler_id)["membership_id"] == "1234-567890"


def test_migrates_version_one_without_losing_bowlers(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        for statement in MIGRATIONS[0]:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
        connection.execute(
            "INSERT INTO bowlers(display_name,name_key,created_at) "
            "VALUES ('Existing Bowler','existing bowler','before')"
        )
    db = BowlerDatabase(path)
    assert db.get(1)["display_name"] == "Existing Bowler"
    assert db.averages(1) == []
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_future_schema_is_not_modified(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="newer version"):
        BowlerDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_online_backup_contains_committed_records(db, member, tmp_path):
    bowler_id, _ = seed(db, member)
    target = tmp_path / "backup.sqlite3"
    db.backup(target)
    assert BowlerDatabase(target).get(bowler_id)["display_name"] == "Alex Bowler"


def test_schema_migration_rolls_back_on_failure(tmp_path, monkeypatch):
    import usbc_average_lookup.database as module

    monkeypatch.setattr(module, "MIGRATIONS", ((*MIGRATIONS[0], "BROKEN SQL"), MIGRATIONS[1]))
    path = tmp_path / "rollback.sqlite3"
    with pytest.raises(sqlite3.Error):
        BowlerDatabase(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )
