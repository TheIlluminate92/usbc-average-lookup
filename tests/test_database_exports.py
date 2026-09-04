import csv
from dataclasses import replace

import pytest
from openpyxl import load_workbook

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.models import CompositeAverage, InputBowler, Member
from usbc_average_lookup.services.database_exports import (
    BTM_HEADERS,
    AverageRule,
    export_database,
    export_preview,
)


@pytest.fixture
def stored(tmp_path):
    db = BowlerDatabase(tmp_path / "db")
    bowler_id = db.import_bowlers([InputBowler("Alex Bowler", "1234-000567")]).added[0]
    member = Member("1", "1234", "000567", "Alex", "Bowler", True, middle_initial="Q", gender="M")
    average = CompositeAverage("2025", 60, 190, False, False)
    db.save_refresh(
        bowler_id,
        member,
        [
            average,
            replace(average, year="2026", average=180),
            replace(average, sport=True, average=200),
            replace(average, challenge=True, average=195),
        ],
        {},
    )
    return db, bowler_id


def test_btm_exact_headers_and_selected_games(stored, tmp_path):
    db, bowler_id = stored
    output = tmp_path / "btm.csv"
    before = db.averages(bowler_id, history=True)
    preview = export_preview(db, [bowler_id], AverageRule())
    export_database(output, preview)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == BTM_HEADERS
    assert rows[1] == ["Alex", "Q", "Bowler", "M", "180", "60", "1234-000567"]
    assert db.averages(bowler_id, history=True) == before


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (AverageRule(mode="Highest"), 190),
        (AverageRule(mode="Specific year", year="2025"), 190),
        (AverageRule(kind="Sport"), 200),
        (AverageRule(kind="Challenge"), 195),
        (AverageRule(minimum_games=61), None),
        (AverageRule(mode="Specific year", year="1999"), None),
        (AverageRule(hand="L"), None),
    ],
)
def test_export_rules_use_only_matching_records(stored, rule, expected):
    db, bowler_id = stored
    average = export_preview(db, [bowler_id], rule)[0]["average"]
    assert (average["average"] if average else None) == expected


def test_manual_selection_checks_record_belongs_to_bowler(stored):
    db, bowler_id = stored
    row = db.averages(bowler_id)[-1]
    assert (
        export_preview(db, [bowler_id], AverageRule("Manual"), {bowler_id: row["id"]})[0][
            "average"
        ]["id"]
        == row["id"]
    )
    assert (
        export_preview(db, [bowler_id], AverageRule("Manual"), {bowler_id: 999})[0]["average"]
        is None
    )


def test_missing_policy_never_silently_substitutes_zero(stored, tmp_path):
    db, bowler_id = stored
    preview = export_preview(db, [bowler_id], AverageRule(minimum_games=999))
    target = tmp_path / "existing.csv"
    target.write_text("original")
    with pytest.raises(ValueError, match="no matching average"):
        export_database(target, preview)
    assert target.read_text() == "original"
    export_database(target, preview, missing="Blank")
    with target.open(encoding="utf-8-sig") as handle:
        row = list(csv.reader(handle))[1]
    assert row[4:6] == ["", ""]
    with pytest.raises(ValueError, match="No bowlers"):
        export_database(target, preview, missing="Skip")


def test_generic_xlsx_retains_text_ids_and_rule_context(stored, tmp_path):
    db, bowler_id = stored
    target = tmp_path / "bowlers.xlsx"
    export_database(target, export_preview(db, [bowler_id], AverageRule()), format="XLSX")
    workbook = load_workbook(target)
    sheet = workbook.active
    assert sheet["G2"].value == "1234-000567"
    assert sheet["H2"].value == "2026"
    assert sheet["I2"].value == "Standard"
    assert sheet.freeze_panes == "A2"
    workbook.close()


def test_csv_quotes_names_and_neutralizes_formulas(stored, tmp_path):
    db, bowler_id = stored
    preview = export_preview(db, [bowler_id], AverageRule())
    preview[0]["bowler"]["first_name"] = "=DANGEROUS()"
    preview[0]["bowler"]["last_name"] = "Bowler, Jr."
    target = tmp_path / "safe.csv"
    export_database(target, preview)
    with target.open(encoding="utf-8-sig", newline="") as handle:
        row = list(csv.reader(handle))[1]
    assert row[0] == "'=DANGEROUS()"
    assert row[2] == "Bowler, Jr."
