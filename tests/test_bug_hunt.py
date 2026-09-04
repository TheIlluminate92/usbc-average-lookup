"""Regressions discovered during the 0.4.3 bug hunt."""

import csv
import json
import os

import pytest

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.models import InputBowler, Member
from usbc_average_lookup.services.database_exports import (
    AverageRule,
    export_database,
    export_preview,
)
from usbc_average_lookup.services.input_parser import (
    parse_input_file,
    parse_input_json,
    parse_input_text,
)


def test_corrected_name_is_used_by_export(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Wrong Q Name")]).added[0]
    db.set_identity(bowler_id, "Correct R Bowler", "")
    output = tmp_path / "corrected.csv"
    export_database(output, export_preview(db, [bowler_id], AverageRule()), missing="Blank")
    with output.open(encoding="utf-8-sig") as stream:
        assert list(csv.reader(stream))[1][:3] == ["Correct", "R", "Bowler"]


def test_unchanged_official_name_keeps_normalized_parts(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Alex van Buren", "1234-1")]).added[0]
    member = Member("1", "1234", "1", "Alex", "van Buren", True, middle_initial="Q")
    db.save_refresh(bowler_id, member, [], {})
    db.set_identity(bowler_id, member.display_name, "1234-1")
    assert db.get(bowler_id)["last_name"] == "van Buren"
    assert db.get(bowler_id)["middle_initial"] == "Q"


@pytest.mark.parametrize(
    "text",
    [
        "First Name,Middle Initial,Last Name,USBC ID Number\nAlex,Q,Bowler,1234-1",
        "First Name\tMiddle Name\tLast Name\tUSBC ID\nAlex\tQuinn\tBowler\t1234-1",
    ],
)
def test_split_name_import_keeps_middle_name(text):
    assert parse_input_text(text)[0].name in ("Alex Q Bowler", "Alex Quinn Bowler")


def test_json_split_name_keeps_middle_initial():
    rows = parse_input_json(
        json.dumps([{"firstName": "Alex", "middleInitial": "Q", "lastName": "Bowler"}])
    )
    assert rows[0].name == "Alex Q Bowler"


@pytest.mark.parametrize("text", ["USBC ID\n1234-1", "1234-1", "USBC ID Number\n1234-1\n1234-2"])
def test_one_column_usbc_ids_are_not_names(text):
    rows = parse_input_text(text)
    assert rows[0] == InputBowler("", "1234-1")
    assert all(row.membership_id and not row.name for row in rows)


def test_corrupt_workbook_returns_friendly_validation_error(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_text("not a workbook")
    with pytest.raises(ValueError, match="Excel"):
        parse_input_file(path)


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
def test_database_destination_guard_covers_live_files(tmp_path, suffix):
    db = BowlerDatabase(tmp_path / "db.sqlite3")
    with pytest.raises(ValueError, match="database"):
        db.validate_destination(tmp_path / ("db.sqlite3" + suffix))
    db.validate_destination(tmp_path / "safe.csv")


def test_backup_rejects_hard_link_to_live_database(tmp_path):
    db = BowlerDatabase(tmp_path / "db.sqlite3")
    alias = tmp_path / "alias.sqlite3"
    os.link(db.path, alias)
    with pytest.raises(ValueError, match="database"):
        db.backup(alias)


def test_alias_matching_finds_the_original_person_only(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Alex Oldname")]).added[0]
    db.save_refresh(bowler_id, Member("1", "1234", "1", "Alex", "Newname", True), [], {})
    db.import_bowlers([InputBowler("Alex Oldname Junior", "1234-2")])
    assert [row["id"] for row in db.find_name_matches("Alex Oldname")] == [bowler_id]


def test_reused_id_keeps_new_import_name_as_alias(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Alex Bowler", "1234-1")]).added[0]
    db.import_bowlers([InputBowler("Alex Newname", "1234-1")])
    assert db.find_name_matches("Alex Newname")[0]["id"] == bowler_id
