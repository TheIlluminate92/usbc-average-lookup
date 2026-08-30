from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from usbc_average_lookup.models import InputBowler

_LINE_PATTERN = re.compile(
    r"^\s*(?P<name>.+?)\s*\(\s*[*_]*(?P<id>\d{4}-\d+)[*_]*\s*\)\s*$"
)
_NAME_HEADERS = {"name", "bowler", "bowler name", "fullname", "full name"}
_ID_HEADERS = {
    "id",
    "member id",
    "member number",
    "membership id",
    "membership number",
    "usbc id",
    "usbc number",
}


def parse_input_file(path: Path) -> list[InputBowler]:
    return parse_input_text(path.read_text(encoding="utf-8-sig"))


def parse_input_text(text: str) -> list[InputBowler]:
    """Parse either ``Name (prefix-suffix)`` lines or delimited rows.

    Delimited input may use commas, tabs, pipes, or semicolons. A header is
    optional; without one, column 1 is the name and column 2 is the optional
    membership ID.
    """

    cleaned = [line.strip() for line in text.splitlines() if line.strip()]
    if not cleaned:
        return []

    if not any(delimiter in "\n".join(cleaned) for delimiter in (",", "\t", "|", ";")):
        line_matches = [_LINE_PATTERN.match(line) for line in cleaned]
        return [
            InputBowler(
                match.group("name").strip() if match else line,
                match.group("id") if match else "",
            )
            for line, match in zip(cleaned, line_matches, strict=True)
        ]

    delimiter = _detect_delimiter("\n".join(cleaned))
    rows = list(csv.reader(io.StringIO("\n".join(cleaned)), delimiter=delimiter))
    if not rows:
        return []

    normalized_header = [cell.strip().casefold() for cell in rows[0]]
    name_index = _find_header(normalized_header, _NAME_HEADERS)
    id_index = _find_header(normalized_header, _ID_HEADERS)
    data_rows = rows[1:] if name_index is not None else rows
    name_index = 0 if name_index is None else name_index

    bowlers: list[InputBowler] = []
    for row_number, row in enumerate(data_rows, start=2 if data_rows is not rows else 1):
        if name_index >= len(row) or not row[name_index].strip():
            raise ValueError(f"Row {row_number} is missing a bowler name")
        membership_id = ""
        fallback_id_index = 1 if id_index is None and len(row) > 1 else id_index
        if fallback_id_index is not None and fallback_id_index < len(row):
            membership_id = _clean_membership_id(row[fallback_id_index])
        bowlers.append(InputBowler(row[name_index].strip(), membership_id))
    return bowlers


def _detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=",\t|;").delimiter
    except csv.Error:
        return "\t"


def _find_header(header: list[str], aliases: set[str]) -> int | None:
    return next((index for index, value in enumerate(header) if value in aliases), None)


def _clean_membership_id(value: str) -> str:
    return value.strip().strip("() ").strip("*_").strip()
