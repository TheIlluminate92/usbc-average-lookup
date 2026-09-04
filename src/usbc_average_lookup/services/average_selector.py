from collections.abc import Iterable

from usbc_average_lookup.models import CompositeAverage


def select_latest_standard(
    records: Iterable[CompositeAverage],
) -> CompositeAverage | None:
    """Return the newest non-sport, non-challenge composite with games.

    BOWL.com's observed ``year`` value is numeric text and maps to the ending
    year displayed for the bowling season. Season labeling remains presentation
    metadata; selection only needs a safe numeric ordering.
    """

    eligible = [
        record
        for record in records
        if not record.sport and not record.challenge and record.games > 0
    ]
    if not eligible:
        return None

    def year_key(record: CompositeAverage) -> int:
        try:
            return int(record.year)
        except ValueError as error:
            raise ValueError(f"Unexpected composite-average year: {record.year!r}") from error

    return max(eligible, key=year_key)
