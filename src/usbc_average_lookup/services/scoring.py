from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from usbc_average_lookup.services.registration import (
    Competition,
    RegistrationDataError,
    RegistrationStore,
    RosterRole,
)


class SessionStatus(StrEnum):
    DRAFT = "Draft"
    FINAL = "Final"


class GameStatus(StrEnum):
    NOT_ENTERED = "Not entered"
    BOWLED = "Bowled"
    ABSENT = "Absent"
    BLIND = "Blind"
    VACANCY = "Vacancy"


@dataclass(frozen=True, slots=True)
class LeagueSession:
    id: str
    competition_id: str
    week_number: int
    bowled_on: str
    label: str
    games_per_player: int
    status: SessionStatus
    created_at: str
    updated_at: str

    @property
    def display_name(self) -> str:
        detail = self.label or self.bowled_on
        return f"Week {self.week_number}" + (f" — {detail}" if detail else "")


@dataclass(frozen=True, slots=True)
class ScoreLine:
    id: str
    session_id: str
    registration_id: str
    bowler_id: str
    team_id: str
    player_name: str
    team_name: str
    roster_role: RosterRole
    entering_average: int
    handicap: int
    lineup_order: int
    is_vacancy: bool


@dataclass(frozen=True, slots=True)
class GameScore:
    id: str
    score_line_id: str
    game_number: int
    status: GameStatus
    scratch_score: int | None
    pins_counted: int


@dataclass(frozen=True, slots=True)
class ScoreLineView:
    line: ScoreLine
    games: tuple[GameScore, ...]

    @property
    def scratch_total(self) -> int:
        return sum(game.scratch_score or 0 for game in self.games)

    @property
    def counted_total(self) -> int:
        return sum(game.pins_counted for game in self.games)


@dataclass(frozen=True, slots=True)
class TeamGameTotals:
    team_id: str
    team_name: str
    scratch: tuple[int, ...]
    counted: tuple[int, ...]

    @property
    def scratch_total(self) -> int:
        return sum(self.scratch)

    @property
    def counted_total(self) -> int:
        return sum(self.counted)


@dataclass(frozen=True, slots=True)
class ScoreChange:
    id: str
    session_id: str
    score_line_id: str
    game_number: int
    team_id: str
    player_name: str
    team_name: str
    old_status: str
    old_scratch_score: int | None
    old_pins_counted: int
    old_entering_average: int
    old_handicap: int
    new_status: str
    new_scratch_score: int | None
    new_pins_counted: int
    new_entering_average: int
    new_handicap: int
    reason: str
    changed_at: str


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session: LeagueSession
    player_rows: int
    games_entered: int
    total_games: int
    scratch_total: int
    counted_total: int
    correction_count: int


class ScoringStore:
    def __init__(self, registrations: RegistrationStore) -> None:
        self.registrations = registrations

    def list_sessions(self, competition_id: str) -> list[LeagueSession]:
        self.registrations._competition(competition_id)
        with closing(self.registrations._connect()) as connection:
            self.registrations._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT id, competition_id, week_number, bowled_on, label,
                       games_per_player, status, created_at, updated_at
                FROM league_sessions
                WHERE competition_id = ?
                ORDER BY week_number DESC
                """,
                (competition_id,),
            )
            return [_session_from_row(row) for row in rows]

    def create_session(
        self,
        competition_id: str,
        week_number: int,
        bowled_on: str = "",
        label: str = "",
    ) -> LeagueSession:
        competition = self.registrations._competition(competition_id)
        if week_number <= 0:
            raise RegistrationDataError("Week number must be greater than zero")
        clean_date = bowled_on.strip()
        if clean_date:
            try:
                date.fromisoformat(clean_date)
            except ValueError as error:
                raise RegistrationDataError("Date must use YYYY-MM-DD") from error
        timestamp = _now()
        session = LeagueSession(
            id=_new_id(),
            competition_id=competition.id,
            week_number=week_number,
            bowled_on=clean_date,
            label=label.strip(),
            games_per_player=competition.games_per_session,
            status=SessionStatus.DRAFT,
            created_at=timestamp,
            updated_at=timestamp,
        )
        roster = [
            view
            for view in self.registrations.registration_views(competition.id)
            if not view.registration.withdrawn
            and view.registration.roster_role is RosterRole.REGULAR
            and view.team is not None
        ]
        order_by_team: dict[str, int] = {}
        try:
            with closing(self.registrations._connect()) as connection:
                self.registrations._ensure_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO league_sessions (
                        id, competition_id, week_number, bowled_on, label,
                        games_per_player, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.id,
                        session.competition_id,
                        session.week_number,
                        session.bowled_on,
                        session.label,
                        session.games_per_player,
                        session.status.value,
                        session.created_at,
                        session.updated_at,
                    ),
                )
                for view in roster:
                    team = view.team
                    assert team is not None
                    order_by_team[team.id] = order_by_team.get(team.id, 0) + 1
                    average = (
                        self.registrations.competition_average(
                            competition, view.registration
                        )
                        or 0
                    )
                    handicap = self.registrations.competition_handicap(
                        competition, average
                    )
                    self._insert_line(
                        connection,
                        session,
                        registration_id=view.registration.id,
                        bowler_id=view.bowler.id,
                        team_id=team.id,
                        player_name=view.bowler.name,
                        team_name=team.name,
                        roster_role=view.registration.roster_role,
                        entering_average=average,
                        handicap=handicap,
                        lineup_order=order_by_team[team.id],
                        is_vacancy=False,
                    )
                connection.commit()
        except sqlite3.IntegrityError as error:
            if "league_sessions.competition_id, league_sessions.week_number" in str(
                error
            ):
                raise RegistrationDataError(
                    f"Week {week_number} already exists for {competition.display_name}"
                ) from error
            raise RegistrationDataError(f"Score sheet could not be created: {error}") from error
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Score sheet could not be created: {error}") from error
        self.registrations._notify_change()
        return session

    def session_history(
        self, competition_id: str, team_id: str = ""
    ) -> list[SessionSummary]:
        summaries: list[SessionSummary] = []
        for session in self.list_sessions(competition_id):
            sheet = self.score_sheet(session.id)
            totals = self.team_totals(session.id)
            if team_id:
                sheet = [view for view in sheet if view.line.team_id == team_id]
                totals = [item for item in totals if item.team_id == team_id]
                if not sheet:
                    continue
            changes = self.change_log(session.id)
            if team_id:
                changes = [change for change in changes if change.team_id == team_id]
            summaries.append(
                SessionSummary(
                    session=session,
                    player_rows=len(sheet),
                    games_entered=sum(
                        game.status is not GameStatus.NOT_ENTERED
                        for view in sheet
                        for game in view.games
                    ),
                    total_games=len(sheet) * session.games_per_player,
                    scratch_total=sum(item.scratch_total for item in totals),
                    counted_total=sum(item.counted_total for item in totals),
                    correction_count=len(changes),
                )
            )
        return summaries

    def score_sheet(self, session_id: str) -> list[ScoreLineView]:
        with closing(self.registrations._connect()) as connection:
            self.registrations._ensure_schema(connection)
            lines = [
                _line_from_row(row)
                for row in connection.execute(
                    """
                    SELECT id, session_id, registration_id, bowler_id, team_id,
                           player_name, team_name, roster_role, entering_average,
                           handicap, lineup_order, is_vacancy
                    FROM score_lines
                    WHERE session_id = ?
                    ORDER BY team_name COLLATE NOCASE, lineup_order, player_name COLLATE NOCASE
                    """,
                    (session_id,),
                )
            ]
            games_by_line: dict[str, list[GameScore]] = {line.id: [] for line in lines}
            if lines:
                placeholders = ",".join("?" for _line in lines)
                for row in connection.execute(
                    f"""
                    SELECT id, score_line_id, game_number, status, scratch_score,
                           pins_counted
                    FROM game_scores
                    WHERE score_line_id IN ({placeholders})
                    ORDER BY game_number
                    """,
                    tuple(line.id for line in lines),
                ):
                    games_by_line[row["score_line_id"]].append(_game_from_row(row))
        return [
            ScoreLineView(line, tuple(games_by_line[line.id])) for line in lines
        ]

    def get_session(self, session_id: str) -> LeagueSession:
        with closing(self.registrations._connect()) as connection:
            self.registrations._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT id, competition_id, week_number, bowled_on, label,
                       games_per_player, status, created_at, updated_at
                FROM league_sessions WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise RegistrationDataError("Score sheet was not found")
        return _session_from_row(row)

    def add_registered_player(
        self, session_id: str, registration_id: str, team_id: str
    ) -> None:
        session = self.get_session(session_id)
        self._require_draft(session)
        competition = self.registrations._competition(session.competition_id)
        registration = self.registrations._registration(registration_id)
        if registration.competition_id != session.competition_id:
            raise RegistrationDataError("That player belongs to another league")
        team = self.registrations._team(team_id)
        if team.competition_id != session.competition_id:
            raise RegistrationDataError("That team belongs to another league")
        bowler = self.registrations._bowler(registration.bowler_id)
        average = self.registrations.competition_average(competition, registration) or 0
        handicap = self.registrations.competition_handicap(competition, average)
        try:
            with closing(self.registrations._connect()) as connection:
                self.registrations._ensure_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                lineup_order = self._next_lineup_order(connection, session.id, team.id)
                self._insert_line(
                    connection,
                    session,
                    registration_id=registration.id,
                    bowler_id=bowler.id,
                    team_id=team.id,
                    player_name=bowler.name,
                    team_name=team.name,
                    roster_role=registration.roster_role,
                    entering_average=average,
                    handicap=handicap,
                    lineup_order=lineup_order,
                    is_vacancy=False,
                )
                self._touch_session(connection, session.id)
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise RegistrationDataError(
                f"{bowler.name} is already on this score sheet"
            ) from error
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Player could not be added: {error}") from error
        self.registrations._notify_change()

    def add_vacancy(self, session_id: str, team_id: str) -> None:
        session = self.get_session(session_id)
        self._require_draft(session)
        competition = self.registrations._competition(session.competition_id)
        team = self.registrations._team(team_id)
        if team.competition_id != session.competition_id:
            raise RegistrationDataError("That team belongs to another league")
        average = competition.vacancy_score
        handicap = self.registrations.competition_handicap(competition, average)
        try:
            with closing(self.registrations._connect()) as connection:
                self.registrations._ensure_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                lineup_order = self._next_lineup_order(connection, session.id, team.id)
                self._insert_line(
                    connection,
                    session,
                    registration_id="",
                    bowler_id="",
                    team_id=team.id,
                    player_name=f"Vacancy {lineup_order}",
                    team_name=team.name,
                    roster_role=RosterRole.REGULAR,
                    entering_average=average,
                    handicap=handicap,
                    lineup_order=lineup_order,
                    is_vacancy=True,
                    initial_status=GameStatus.VACANCY,
                    competition=competition,
                )
                self._touch_session(connection, session.id)
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Vacancy could not be added: {error}") from error
        self.registrations._notify_change()

    def remove_line(self, line_id: str, reason: str = "") -> None:
        line, session = self._line_and_session(line_id)
        self._require_draft(session)
        view = next(
            item for item in self.score_sheet(session.id) if item.line.id == line.id
        )
        entered_games = [
            game for game in view.games if game.status is not GameStatus.NOT_ENTERED
        ]
        clean_reason = reason.strip()
        if entered_games and not clean_reason:
            raise RegistrationDataError(
                "Enter a reason for removing a player with saved scores"
            )
        try:
            with closing(self.registrations._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for game in entered_games:
                    connection.execute(
                        """
                        INSERT INTO score_change_log (
                            id, session_id, score_line_id, game_number,
                            team_id, player_name, team_name, old_status, old_scratch_score,
                            old_pins_counted, old_entering_average, old_handicap,
                            new_status, reason, changed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            _new_id(),
                            session.id,
                            line.id,
                            game.game_number,
                            line.team_id,
                            line.player_name,
                            line.team_name,
                            game.status.value,
                            game.scratch_score,
                            game.pins_counted,
                            line.entering_average,
                            line.handicap,
                            "Removed",
                            clean_reason,
                            _now(),
                        ),
                    )
                connection.execute(
                    "DELETE FROM game_scores WHERE score_line_id = ?", (line.id,)
                )
                connection.execute("DELETE FROM score_lines WHERE id = ?", (line.id,))
                self._touch_session(connection, session.id)
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Score-sheet row could not be removed: {error}") from error
        self.registrations._notify_change()

    def save_line_scores(
        self,
        line_id: str,
        entering_average: int,
        entries: list[tuple[GameStatus, int | None]],
        change_reason: str = "",
    ) -> None:
        line, session = self._line_and_session(line_id)
        self._require_draft(session)
        if not 0 <= entering_average <= 300:
            raise RegistrationDataError("Entering average must be between 0 and 300")
        if len(entries) != session.games_per_player:
            raise RegistrationDataError(
                f"Enter exactly {session.games_per_player} game results"
            )
        competition = self.registrations._competition(session.competition_id)
        average = competition.vacancy_score if line.is_vacancy else entering_average
        handicap = self.registrations.competition_handicap(competition, average)
        normalized: list[tuple[GameStatus, int | None, int]] = []
        for status, score in entries:
            if line.is_vacancy:
                status = GameStatus.VACANCY
            if status is GameStatus.BOWLED:
                if score is None or not 0 <= score <= 300:
                    raise RegistrationDataError("Bowled games require a score from 0 to 300")
                scratch = score
                counted = score + handicap
            elif status is GameStatus.BLIND:
                scratch = max(average - competition.blind_penalty, 0)
                counted = scratch + handicap
            elif status is GameStatus.VACANCY:
                scratch = competition.vacancy_score
                counted = scratch + handicap
            elif status in (GameStatus.ABSENT, GameStatus.NOT_ENTERED):
                scratch = None
                counted = 0
            else:
                raise RegistrationDataError("Unknown game status")
            normalized.append((status, scratch, counted))
        try:
            with closing(self.registrations._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                old_games = [
                    _game_from_row(row)
                    for row in connection.execute(
                        """
                        SELECT id, score_line_id, game_number, status, scratch_score,
                               pins_counted
                        FROM game_scores
                        WHERE score_line_id = ?
                        ORDER BY game_number
                        """,
                        (line.id,),
                    )
                ]
                corrections: list[
                    tuple[GameScore, GameStatus, int | None, int]
                ] = []
                for old_game, (new_status, new_scratch, new_counted) in zip(
                    old_games, normalized, strict=True
                ):
                    changed = (
                        old_game.status is not new_status
                        or old_game.scratch_score != new_scratch
                        or old_game.pins_counted != new_counted
                        or line.entering_average != average
                        or line.handicap != handicap
                    )
                    if changed and old_game.status is not GameStatus.NOT_ENTERED:
                        corrections.append(
                            (old_game, new_status, new_scratch, new_counted)
                        )
                clean_reason = change_reason.strip()
                if corrections and not clean_reason:
                    raise RegistrationDataError(
                        "Enter a reason for changing previously saved scores"
                    )
                connection.execute(
                    """
                    UPDATE score_lines
                    SET entering_average = ?, handicap = ?
                    WHERE id = ?
                    """,
                    (average, handicap, line.id),
                )
                for game_number, (status, scratch, counted) in enumerate(
                    normalized, start=1
                ):
                    connection.execute(
                        """
                        UPDATE game_scores
                        SET status = ?, scratch_score = ?, pins_counted = ?
                        WHERE score_line_id = ? AND game_number = ?
                        """,
                        (status.value, scratch, counted, line.id, game_number),
                    )
                for old_game, status, scratch, counted in corrections:
                    connection.execute(
                        """
                        INSERT INTO score_change_log (
                            id, session_id, score_line_id, game_number,
                            team_id, player_name, team_name, old_status, old_scratch_score,
                            old_pins_counted, old_entering_average, old_handicap,
                            new_status, new_scratch_score, new_pins_counted,
                            new_entering_average, new_handicap, reason, changed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            _new_id(),
                            session.id,
                            line.id,
                            old_game.game_number,
                            line.team_id,
                            line.player_name,
                            line.team_name,
                            old_game.status.value,
                            old_game.scratch_score,
                            old_game.pins_counted,
                            line.entering_average,
                            line.handicap,
                            status.value,
                            scratch,
                            counted,
                            average,
                            handicap,
                            clean_reason,
                            _now(),
                        ),
                    )
                self._touch_session(connection, session.id)
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Scores could not be saved: {error}") from error
        self.registrations._notify_change()

    def team_totals(self, session_id: str) -> list[TeamGameTotals]:
        session = self.get_session(session_id)
        totals: dict[str, tuple[str, list[int], list[int]]] = {}
        for view in self.score_sheet(session_id):
            team = totals.setdefault(
                view.line.team_id,
                (
                    view.line.team_name,
                    [0] * session.games_per_player,
                    [0] * session.games_per_player,
                ),
            )
            for game in view.games:
                team[1][game.game_number - 1] += game.scratch_score or 0
                team[2][game.game_number - 1] += game.pins_counted
        return [
            TeamGameTotals(team_id, name, tuple(scratch), tuple(counted))
            for team_id, (name, scratch, counted) in sorted(
                totals.items(), key=lambda item: item[1][0].casefold()
            )
        ]

    def finalize_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        self._require_draft(session)
        sheet = self.score_sheet(session.id)
        if not sheet:
            raise RegistrationDataError("Add players before finalizing this score sheet")
        missing = sum(
            game.status is GameStatus.NOT_ENTERED
            for view in sheet
            for game in view.games
        )
        if missing:
            raise RegistrationDataError(
                f"{missing} game result{'s are' if missing != 1 else ' is'} still missing"
            )
        with closing(self.registrations._connect()) as connection:
            link = connection.execute(
                "SELECT round_id FROM round_score_links WHERE session_id = ?", (session.id,)
            ).fetchone()
            if link:
                matches = connection.execute(
                    "SELECT left_team_id, right_team_id FROM competition_matches "
                    "WHERE round_id = ?",
                    (link[0],),
                ).fetchall()
                expected = {team for match in matches for team in match if team}
                required = {team for match in matches if match[1] for team in match}
                actual = {view.line.team_id for view in sheet}
                if not required <= actual or not actual <= expected:
                    raise RegistrationDataError(
                        "Every scheduled opponent needs a score row; "
                        "remove teams that are not in this round before finalizing"
                    )
        self._set_session_status(session.id, SessionStatus.FINAL)

    def linked_round_number(self, session_id: str) -> int | None:
        with closing(self.registrations._connect()) as connection:
            row = connection.execute(
                "SELECT r.round_number FROM round_score_links l "
                "JOIN competition_rounds r ON r.id = l.round_id WHERE l.session_id = ?",
                (session_id,),
            ).fetchone()
        return row[0] if row else None

    def reopen_session(self, session_id: str, reason: str) -> None:
        session = self.get_session(session_id)
        if session.status is SessionStatus.DRAFT:
            return
        clean_reason = reason.strip()
        if not clean_reason:
            raise RegistrationDataError("Enter a reason for reopening this score sheet")
        try:
            with closing(self.registrations._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE league_sessions SET status = ?, updated_at = ? WHERE id = ?",
                    (SessionStatus.DRAFT.value, _now(), session.id),
                )
                connection.execute(
                    """
                    INSERT INTO score_change_log (
                        id, session_id, old_status, new_status, reason, changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(),
                        session.id,
                        SessionStatus.FINAL.value,
                        SessionStatus.DRAFT.value,
                        clean_reason,
                        _now(),
                    ),
                )
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Score sheet could not be reopened: {error}") from error
        self.registrations._notify_change()

    def change_log(self, session_id: str) -> list[ScoreChange]:
        self.get_session(session_id)
        with closing(self.registrations._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, score_line_id, game_number, team_id,
                       player_name, team_name, old_status, old_scratch_score, old_pins_counted,
                       old_entering_average, old_handicap, new_status,
                       new_scratch_score, new_pins_counted, new_entering_average,
                       new_handicap, reason, changed_at
                FROM score_change_log
                WHERE session_id = ?
                ORDER BY changed_at DESC, game_number
                """,
                (session_id,),
            )
            return [ScoreChange(**dict(row)) for row in rows]

    def _set_session_status(self, session_id: str, status: SessionStatus) -> None:
        try:
            with closing(self.registrations._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE league_sessions SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, _now(), session_id),
                )
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(f"Score sheet could not be updated: {error}") from error
        self.registrations._notify_change()

    def _insert_line(
        self,
        connection: sqlite3.Connection,
        session: LeagueSession,
        *,
        registration_id: str,
        bowler_id: str,
        team_id: str,
        player_name: str,
        team_name: str,
        roster_role: RosterRole,
        entering_average: int,
        handicap: int,
        lineup_order: int,
        is_vacancy: bool,
        initial_status: GameStatus = GameStatus.NOT_ENTERED,
        competition: Competition | None = None,
    ) -> None:
        line_id = _new_id()
        connection.execute(
            """
            INSERT INTO score_lines (
                id, session_id, registration_id, bowler_id, team_id, player_name,
                team_name, roster_role, entering_average, handicap, lineup_order,
                is_vacancy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                line_id,
                session.id,
                registration_id,
                bowler_id,
                team_id,
                player_name,
                team_name,
                roster_role.value,
                entering_average,
                handicap,
                lineup_order,
                int(is_vacancy),
            ),
        )
        for game_number in range(1, session.games_per_player + 1):
            scratch = None
            counted = 0
            if initial_status is GameStatus.VACANCY:
                assert competition is not None
                scratch = competition.vacancy_score
                counted = scratch + handicap
            connection.execute(
                """
                INSERT INTO game_scores (
                    id, score_line_id, game_number, status, scratch_score, pins_counted
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id(),
                    line_id,
                    game_number,
                    initial_status.value,
                    scratch,
                    counted,
                ),
            )

    @staticmethod
    def _next_lineup_order(
        connection: sqlite3.Connection, session_id: str, team_id: str
    ) -> int:
        value = connection.execute(
            """
            SELECT COALESCE(MAX(lineup_order), 0) + 1
            FROM score_lines WHERE session_id = ? AND team_id = ?
            """,
            (session_id, team_id),
        ).fetchone()[0]
        return int(value)

    @staticmethod
    def _touch_session(connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            "UPDATE league_sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )

    def _line_and_session(self, line_id: str) -> tuple[ScoreLine, LeagueSession]:
        with closing(self.registrations._connect()) as connection:
            self.registrations._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT id, session_id, registration_id, bowler_id, team_id,
                       player_name, team_name, roster_role, entering_average,
                       handicap, lineup_order, is_vacancy
                FROM score_lines WHERE id = ?
                """,
                (line_id,),
            ).fetchone()
        if row is None:
            raise RegistrationDataError("Score-sheet row was not found")
        line = _line_from_row(row)
        return line, self.get_session(line.session_id)

    @staticmethod
    def _require_draft(session: LeagueSession) -> None:
        if session.status is SessionStatus.FINAL:
            raise RegistrationDataError(
                "This score sheet is final. Reopen it before making corrections."
            )


def _session_from_row(row: sqlite3.Row) -> LeagueSession:
    return LeagueSession(
        id=row["id"],
        competition_id=row["competition_id"],
        week_number=row["week_number"],
        bowled_on=row["bowled_on"],
        label=row["label"],
        games_per_player=row["games_per_player"],
        status=SessionStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _line_from_row(row: sqlite3.Row) -> ScoreLine:
    return ScoreLine(
        id=row["id"],
        session_id=row["session_id"],
        registration_id=row["registration_id"],
        bowler_id=row["bowler_id"],
        team_id=row["team_id"],
        player_name=row["player_name"],
        team_name=row["team_name"],
        roster_role=RosterRole(row["roster_role"]),
        entering_average=row["entering_average"],
        handicap=row["handicap"],
        lineup_order=row["lineup_order"],
        is_vacancy=bool(row["is_vacancy"]),
    )


def _game_from_row(row: sqlite3.Row) -> GameScore:
    return GameScore(
        id=row["id"],
        score_line_id=row["score_line_id"],
        game_number=row["game_number"],
        status=GameStatus(row["status"]),
        scratch_score=row["scratch_score"],
        pins_counted=row["pins_counted"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid4().hex
