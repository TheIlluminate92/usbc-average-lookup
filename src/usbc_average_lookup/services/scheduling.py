from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from usbc_average_lookup.services.registration import (
    CompetitionFormat,
    RegistrationDataError,
    RegistrationStore,
    Team,
)


class RoundStatus(StrEnum):
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In progress"
    FINAL = "Final"
    POSTPONED = "Postponed"
    CANCELLED = "Cancelled"


class MatchStatus(StrEnum):
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In progress"
    FINAL = "Final"
    POSTPONED = "Postponed"
    FORFEIT = "Forfeit"
    CANCELLED = "Cancelled"


@dataclass(frozen=True, slots=True)
class CompetitionRound:
    id: str
    competition_id: str
    round_number: int
    label: str
    scheduled_on: str
    stage: str
    status: RoundStatus
    created_at: str

    @property
    def display_name(self) -> str:
        detail = self.label or self.scheduled_on
        return f"Round {self.round_number}" + (f" — {detail}" if detail else "")


@dataclass(frozen=True, slots=True)
class CompetitionMatch:
    id: str
    round_id: str
    match_number: int
    left_team_id: str
    right_team_id: str
    left_team_name: str
    right_team_name: str
    lane_start: int | None
    status: MatchStatus
    is_position_round: bool

    @property
    def is_bye(self) -> bool:
        return not self.right_team_id

    @property
    def lane_pair(self) -> str:
        if self.is_bye:
            return "BYE"
        if self.lane_start is None:
            return "Unassigned"
        return f"{self.lane_start}–{self.lane_start + 1}"

    @property
    def matchup(self) -> str:
        if self.is_bye:
            return f"{self.left_team_name} — BYE"
        return f"{self.left_team_name} vs {self.right_team_name}"


class ScheduleStore:
    def __init__(self, registrations: RegistrationStore) -> None:
        self.registrations = registrations

    def list_rounds(self, competition_id: str) -> list[CompetitionRound]:
        self.registrations._competition(competition_id)
        with closing(self.registrations._connect()) as connection:
            self.registrations._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT id, competition_id, round_number, label, scheduled_on,
                       stage, status, created_at
                FROM competition_rounds
                WHERE competition_id = ?
                ORDER BY round_number
                """,
                (competition_id,),
            )
            return [_round_from_row(row) for row in rows]

    def list_matches(self, round_id: str) -> list[CompetitionMatch]:
        with closing(self.registrations._connect()) as connection:
            self.registrations._ensure_schema(connection)
            if connection.execute(
                "SELECT 1 FROM competition_rounds WHERE id = ?", (round_id,)
            ).fetchone() is None:
                raise RegistrationDataError("Schedule round was not found")
            rows = connection.execute(
                """
                SELECT id, round_id, match_number, left_team_id,
                       COALESCE(right_team_id, '') AS right_team_id,
                       left_team_name, right_team_name, lane_start, status,
                       is_position_round
                FROM competition_matches
                WHERE round_id = ?
                ORDER BY lane_start IS NULL, lane_start, match_number
                """,
                (round_id,),
            )
            return [_match_from_row(row) for row in rows]

    def generate_round_robin(
        self,
        competition_id: str,
        *,
        first_lane: int = 1,
    ) -> list[CompetitionRound]:
        competition = self.registrations._competition(competition_id)
        if competition.competition_format is not CompetitionFormat.ROUND_ROBIN:
            raise RegistrationDataError(
                "Set the competition format to Round robin before generating this schedule"
            )
        if first_lane < 1:
            raise RegistrationDataError("First lane must be 1 or greater")
        teams = sorted(
            self.registrations.list_teams(competition_id),
            key=lambda item: item.name.casefold(),
        )
        if len(teams) < 2:
            raise RegistrationDataError("Add at least two teams before making a schedule")
        if self.list_rounds(competition_id):
            raise RegistrationDataError(
                "This competition already has a schedule; edit it instead of replacing it"
            )

        slots: list[Team | None] = list(teams)
        if len(slots) % 2:
            slots.append(None)
        generated_at = _now()
        try:
            with closing(self.registrations._connect()) as connection:
                self.registrations._ensure_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                for round_index in range(len(slots) - 1):
                    round_id = _new_id()
                    round_number = round_index + 1
                    connection.execute(
                        """
                        INSERT INTO competition_rounds (
                            id, competition_id, round_number, label, scheduled_on,
                            stage, status, created_at
                        ) VALUES (?, ?, ?, ?, '', 'Regular season', ?, ?)
                        """,
                        (
                            round_id,
                            competition_id,
                            round_number,
                            f"Week {round_number}",
                            RoundStatus.SCHEDULED.value,
                            generated_at,
                        ),
                    )
                    pairings = [
                        (slots[index], slots[-1 - index])
                        for index in range(len(slots) // 2)
                    ]
                    actual_pair_count = sum(
                        left is not None and right is not None
                        for left, right in pairings
                    )
                    actual_index = 0
                    for match_index, (left, right) in enumerate(pairings, start=1):
                        if left is None:
                            left, right = right, left
                        assert left is not None
                        lane_start: int | None = None
                        if right is not None:
                            lane_position = (
                                actual_index + round_index
                            ) % actual_pair_count
                            lane_start = first_lane + (lane_position * 2)
                            actual_index += 1
                        if round_number % 2 == 0 and right is not None:
                            left, right = right, left
                        connection.execute(
                            """
                            INSERT INTO competition_matches (
                                id, round_id, match_number, left_team_id,
                                right_team_id, left_team_name, right_team_name,
                                lane_start, status, is_position_round
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                            """,
                            (
                                _new_id(),
                                round_id,
                                match_index,
                                left.id,
                                right.id if right is not None else None,
                                left.name,
                                right.name if right is not None else "",
                                lane_start,
                                MatchStatus.SCHEDULED.value,
                            ),
                        )
                    slots = [slots[0], slots[-1], *slots[1:-1]]
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Schedule could not be generated: {error}") from error
        self.registrations._notify_change()
        return self.list_rounds(competition_id)

    def update_match_lane(self, match_id: str, lane_start: int) -> None:
        if lane_start < 1:
            raise RegistrationDataError("First lane must be 1 or greater")
        try:
            with closing(self.registrations._connect()) as connection:
                self.registrations._ensure_schema(connection)
                row = connection.execute(
                    """
                    SELECT round_id, right_team_id
                    FROM competition_matches WHERE id = ?
                    """,
                    (match_id,),
                ).fetchone()
                if row is None:
                    raise RegistrationDataError("Matchup was not found")
                if row["right_team_id"] is None:
                    raise RegistrationDataError("A bye does not need a lane assignment")
                duplicate = connection.execute(
                    """
                    SELECT 1 FROM competition_matches
                    WHERE round_id = ? AND id <> ? AND ABS(lane_start - ?) < 2
                    """,
                    (row["round_id"], match_id, lane_start),
                ).fetchone()
                if duplicate is not None:
                    raise RegistrationDataError(
                        f"Lanes {lane_start}–{lane_start + 1} are already assigned this round"
                    )
                connection.execute(
                    "UPDATE competition_matches SET lane_start = ? WHERE id = ?",
                    (lane_start, match_id),
                )
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Lane assignment could not be saved: {error}") from error
        self.registrations._notify_change()


def _round_from_row(row: sqlite3.Row) -> CompetitionRound:
    return CompetitionRound(
        id=row["id"],
        competition_id=row["competition_id"],
        round_number=row["round_number"],
        label=row["label"],
        scheduled_on=row["scheduled_on"],
        stage=row["stage"],
        status=RoundStatus(row["status"]),
        created_at=row["created_at"],
    )


def _match_from_row(row: sqlite3.Row) -> CompetitionMatch:
    return CompetitionMatch(
        id=row["id"],
        round_id=row["round_id"],
        match_number=row["match_number"],
        left_team_id=row["left_team_id"],
        right_team_id=row["right_team_id"],
        left_team_name=row["left_team_name"],
        right_team_name=row["right_team_name"],
        lane_start=row["lane_start"],
        status=MatchStatus(row["status"]),
        is_position_round=bool(row["is_position_round"]),
    )


def _new_id() -> str:
    return uuid4().hex


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
