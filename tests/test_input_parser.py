from usbc_average_lookup.models import InputBowler
from usbc_average_lookup.services.input_parser import parse_input_text


def test_parses_name_and_parenthesized_membership_id_lines() -> None:
    text = """Alex Bowler (1234-567890)
Jamie Bowler (**9876-54321**)
"""

    assert parse_input_text(text) == [
        InputBowler("Alex Bowler", "1234-567890"),
        InputBowler("Jamie Bowler", "9876-54321"),
    ]


def test_parses_csv_with_headers() -> None:
    text = "Name,Membership ID\nAlex Bowler,1234-567890\nJamie Bowler,\n"

    assert parse_input_text(text) == [
        InputBowler("Alex Bowler", "1234-567890"),
        InputBowler("Jamie Bowler", ""),
    ]


def test_parses_headerless_pipe_delimited_text() -> None:
    text = "Alex Bowler|1234-567890\nJamie Bowler|9876-54321\n"

    assert parse_input_text(text) == [
        InputBowler("Alex Bowler", "1234-567890"),
        InputBowler("Jamie Bowler", "9876-54321"),
    ]
