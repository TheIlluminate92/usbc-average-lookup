from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.services.average_rules import (
    AverageCandidate,
    AverageRounding,
    AverageRule,
    AverageSource,
    RuleSource,
    evaluate_average_rule,
)


class CompetitionKind(StrEnum):
    LEAGUE = "League"
    TOURNAMENT = "Tournament"


class CompetitionFormat(StrEnum):
    ROUND_ROBIN = "Round robin"
    SINGLE_ELIMINATION = "Single elimination"
    CUSTOM = "Custom / manual"


class VerificationState(StrEnum):
    NOT_CHECKED = "Not checked"
    CHECKING = "Checking"
    VERIFIED = "Verified"
    NEEDS_REVIEW = "Needs review"
    NOT_FOUND = "Not found"
    NO_AVERAGE = "No average"
    ERROR = "Lookup error"


class RosterRole(StrEnum):
    REGULAR = "Regular"
    SUBSTITUTE = "Substitute"


@dataclass(slots=True)
class Competition:
    id: str
    name: str
    season: str
    kind: CompetitionKind
    created_at: str
    competition_format: CompetitionFormat = CompetitionFormat.ROUND_ROBIN
    archived: bool = False
    player_pool_id: str = ""
    games_per_session: int = 3
    average_rule_name: str = "Standard composite"
    average_minimum_games: int = 0
    average_multiplier: Decimal = Decimal("1")
    average_add_pins: int = 0
    average_rounding: AverageRounding = AverageRounding.NEAREST
    handicap_base: int = 0
    handicap_percent: Decimal = Decimal("0")
    blind_penalty: int = 10
    vacancy_score: int = 120

    @property
    def display_name(self) -> str:
        return f"{self.season}  •  {self.name}" if self.season else self.name

    @property
    def selection_label(self) -> str:
        return f"{self.display_name}  [{self.kind.value}]"


@dataclass(slots=True)
class BowlerProfile:
    id: str
    name: str
    membership_id: str = ""


@dataclass(slots=True)
class PlayerPool:
    id: str
    label: str
    created_at: str
    archived: bool = False


@dataclass(slots=True)
class PlayerPoolEntry:
    pool_id: str
    bowler_id: str


@dataclass(slots=True)
class Team:
    id: str
    competition_id: str
    name: str


@dataclass(slots=True)
class Registration:
    id: str
    competition_id: str
    bowler_id: str
    team_id: str = ""
    roster_role: RosterRole = RosterRole.REGULAR
    verification: VerificationState = VerificationState.NOT_CHECKED
    average: int | None = None
    average_year: str = ""
    games: int | None = None
    note: str = ""
    withdrawn: bool = False
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class RegistrationTarget:
    competition_id: str
    team_id: str = ""
    new_team_name: str = ""
    roster_role: RosterRole = RosterRole.REGULAR


@dataclass(frozen=True, slots=True)
class RegistrationView:
    registration: Registration
    bowler: BowlerProfile
    team: Team | None

    @property
    def status(self) -> str:
        if self.registration.withdrawn:
            return "Withdrawn"
        if self.team is None and self.registration.roster_role is RosterRole.REGULAR:
            return "Unassigned team"
        if self.registration.verification is VerificationState.VERIFIED:
            return "Ready"
        if self.registration.verification is VerificationState.CHECKING:
            return "Looking up average"
        if self.registration.verification is VerificationState.NEEDS_REVIEW:
            return "Multiple matches — review"
        if self.registration.verification is VerificationState.NOT_FOUND:
            return "Bowler not found"
        if self.registration.verification is VerificationState.NO_AVERAGE:
            return "No average available"
        if self.registration.verification is VerificationState.ERROR:
            return "Lookup error"
        if not self.bowler.membership_id:
            return "Missing member ID"
        return "Not checked"


class RegistrationDataError(ValueError):
    pass


def default_registration_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".average-assistant"
    return root / "Bowling Manager" / "bowling-manager.db"


def default_legacy_registration_path() -> Path:
    return default_registration_path().with_name("registration-data.json")


class RegistrationStore:
    DATABASE_SCHEMA_VERSION = 5
    LEGACY_SCHEMA_VERSIONS = {1, 2}

    def __init__(
        self,
        path: Path | None = None,
        legacy_json_path: Path | None = None,
    ) -> None:
        self.path = path or default_registration_path()
        self.legacy_json_path = (
            legacy_json_path
            if legacy_json_path is not None
            else (default_legacy_registration_path() if path is None else None)
        )
        self.competitions: list[Competition] = []
        self.bowlers: list[BowlerProfile] = []
        self.player_pools: list[PlayerPool] = []
        self.player_pool_entries: list[PlayerPoolEntry] = []
        self.teams: list[Team] = []
        self.registrations: list[Registration] = []
        self._change_listeners: list[Callable[[], None]] = []
        if self.path.exists():
            self.load()
        elif self.legacy_json_path and self.legacy_json_path.exists():
            self._migrate_legacy_json(self.legacy_json_path)

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._backup_before_schema_upgrade()
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                self.player_pools = [
                    PlayerPool(
                        id=row["id"],
                        label=row["label"],
                        created_at=row["created_at"],
                        archived=bool(row["archived"]),
                    )
                    for row in connection.execute(
                        "SELECT id, label, created_at, archived FROM player_pools"
                    )
                ]
                self.bowlers = [
                    BowlerProfile(
                        id=row["id"],
                        name=row["name"],
                        membership_id=row["membership_id"],
                    )
                    for row in connection.execute(
                        "SELECT id, name, membership_id FROM bowlers"
                    )
                ]
                self.competitions = [
                    Competition(
                        id=row["id"],
                        name=row["name"],
                        season=row["season"],
                        kind=CompetitionKind(row["kind"]),
                        created_at=row["created_at"],
                        competition_format=CompetitionFormat(
                            row["competition_format"]
                        ),
                        archived=bool(row["archived"]),
                        player_pool_id=row["player_pool_id"] or "",
                        games_per_session=row["games_per_session"],
                        average_rule_name=row["average_rule_name"],
                        average_minimum_games=row["average_minimum_games"],
                        average_multiplier=Decimal(row["average_multiplier"]),
                        average_add_pins=row["average_add_pins"],
                        average_rounding=AverageRounding(row["average_rounding"]),
                        handicap_base=row["handicap_base"],
                        handicap_percent=Decimal(row["handicap_percent"]),
                        blind_penalty=row["blind_penalty"],
                        vacancy_score=row["vacancy_score"],
                    )
                    for row in connection.execute(
                        """
                        SELECT id, name, season, kind, created_at, competition_format,
                               archived,
                               player_pool_id, games_per_session, average_rule_name,
                               average_minimum_games, average_multiplier,
                               average_add_pins, average_rounding, handicap_base,
                               handicap_percent, blind_penalty, vacancy_score
                        FROM competitions
                        """
                    )
                ]
                self.teams = [
                    Team(
                        id=row["id"],
                        competition_id=row["competition_id"],
                        name=row["name"],
                    )
                    for row in connection.execute(
                        "SELECT id, competition_id, name FROM teams"
                    )
                ]
                self.player_pool_entries = [
                    PlayerPoolEntry(pool_id=row["pool_id"], bowler_id=row["bowler_id"])
                    for row in connection.execute(
                        "SELECT pool_id, bowler_id FROM player_pool_entries"
                    )
                ]
                self.registrations = [
                    Registration(
                        id=row["id"],
                        competition_id=row["competition_id"],
                        bowler_id=row["bowler_id"],
                        team_id=row["team_id"] or "",
                        roster_role=RosterRole(row["roster_role"]),
                        verification=VerificationState(
                            VerificationState.NOT_CHECKED
                            if row["verification"] == VerificationState.CHECKING
                            else row["verification"]
                        ),
                        average=row["average"],
                        average_year=row["average_year"],
                        games=row["games"],
                        note=row["note"],
                        withdrawn=bool(row["withdrawn"]),
                        created_at=row["created_at"],
                    )
                    for row in connection.execute(
                        """
                        SELECT id, competition_id, bowler_id, team_id, roster_role,
                               verification, average, average_year, games, note,
                               withdrawn, created_at
                        FROM registrations
                        """
                    )
                ]
            self._validate_references()
        except (sqlite3.DatabaseError, TypeError, ValueError) as error:
            if isinstance(error, RegistrationDataError):
                raise
            raise RegistrationDataError(
                f"Registration data could not be read: {error}"
            ) from error

    def save(self) -> None:
        self._validate_references()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._backup_before_schema_upgrade()
            with closing(self._connect()) as connection:
                self._ensure_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                for table in (
                    "registrations",
                    "player_pool_entries",
                    "teams",
                    "competitions",
                    "player_pools",
                    "bowlers",
                ):
                    connection.execute(f"DELETE FROM {table}")
                connection.executemany(
                    """
                    INSERT INTO player_pools (id, label, created_at, archived)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (item.id, item.label, item.created_at, int(item.archived))
                        for item in self.player_pools
                    ],
                )
                connection.executemany(
                    "INSERT INTO bowlers (id, name, membership_id) VALUES (?, ?, ?)",
                    [
                        (item.id, item.name, item.membership_id)
                        for item in self.bowlers
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO competitions (
                        id, name, season, kind, created_at, competition_format,
                        archived, player_pool_id,
                        games_per_session, average_rule_name, average_minimum_games,
                        average_multiplier, average_add_pins, average_rounding,
                        handicap_base, handicap_percent, blind_penalty, vacancy_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.id,
                            item.name,
                            item.season,
                            item.kind.value,
                            item.created_at,
                            item.competition_format.value,
                            int(item.archived),
                            item.player_pool_id or None,
                            item.games_per_session,
                            item.average_rule_name,
                            item.average_minimum_games,
                            str(item.average_multiplier),
                            item.average_add_pins,
                            item.average_rounding.value,
                            item.handicap_base,
                            str(item.handicap_percent),
                            item.blind_penalty,
                            item.vacancy_score,
                        )
                        for item in self.competitions
                    ],
                )
                connection.executemany(
                    "INSERT INTO teams (id, competition_id, name) VALUES (?, ?, ?)",
                    [(item.id, item.competition_id, item.name) for item in self.teams],
                )
                connection.executemany(
                    """
                    INSERT INTO player_pool_entries (pool_id, bowler_id)
                    VALUES (?, ?)
                    """,
                    [
                        (item.pool_id, item.bowler_id)
                        for item in self.player_pool_entries
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO registrations (
                        id, competition_id, bowler_id, team_id, roster_role,
                        verification, average, average_year, games, note,
                        withdrawn, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.id,
                            item.competition_id,
                            item.bowler_id,
                            item.team_id or None,
                            item.roster_role.value,
                            item.verification.value,
                            item.average,
                            item.average_year,
                            item.games,
                            item.note,
                            int(item.withdrawn),
                            item.created_at,
                        )
                        for item in self.registrations
                    ],
                )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('saved_at', ?)",
                    (_now(),),
                )
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise RegistrationDataError(
                f"Registration data could not be saved: {error}"
            ) from error
        self._notify_change()

    def add_change_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        if listener not in self._change_listeners:
            self._change_listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._change_listeners:
                self._change_listeners.remove(listener)

        return unsubscribe

    def _notify_change(self) -> None:
        for listener in tuple(self._change_listeners):
            listener()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _backup_before_schema_upgrade(self) -> None:
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path)) as source:
            version = int(source.execute("PRAGMA user_version").fetchone()[0])
            if not 0 < version < self.DATABASE_SCHEMA_VERSION:
                return
            backup_path = self.path.with_name(
                f"{self.path.stem}.schema-v{version}-backup{self.path.suffix}"
            )
            if not backup_path.exists():
                with closing(sqlite3.connect(backup_path)) as destination:
                    source.backup(destination)

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > self.DATABASE_SCHEMA_VERSION:
            raise RegistrationDataError(
                "Registration database was created by a newer app version"
            )
        if version == self.DATABASE_SCHEMA_VERSION:
            return
        if version == 4:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS standing_rules (
                    competition_id TEXT PRIMARY KEY,
                    rules_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS round_score_links (
                    round_id TEXT PRIMARY KEY REFERENCES competition_rounds(id),
                    session_id TEXT NOT NULL UNIQUE REFERENCES league_sessions(id),
                    rules_json TEXT NOT NULL,
                    linked_at TEXT NOT NULL
                );
                PRAGMA user_version = 5;
                COMMIT;
                """
            )
            return
        if version == 3:
            competition_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(competitions)")
            }
            connection.execute("BEGIN IMMEDIATE")
            if "competition_format" not in competition_columns:
                connection.execute(
                    """
                    ALTER TABLE competitions ADD COLUMN competition_format TEXT NOT NULL
                        DEFAULT 'Round robin'
                    """
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS competition_rounds (
                    id TEXT PRIMARY KEY,
                    competition_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL CHECK (round_number > 0),
                    label TEXT NOT NULL DEFAULT '',
                    scheduled_on TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT 'Regular season',
                    status TEXT NOT NULL DEFAULT 'Scheduled' CHECK (status IN (
                        'Scheduled', 'In progress', 'Final', 'Postponed', 'Cancelled'
                    )),
                    created_at TEXT NOT NULL,
                    UNIQUE (competition_id, round_number)
                );

                CREATE TABLE IF NOT EXISTS competition_matches (
                    id TEXT PRIMARY KEY,
                    round_id TEXT NOT NULL
                        REFERENCES competition_rounds(id) ON DELETE CASCADE,
                    match_number INTEGER NOT NULL CHECK (match_number > 0),
                    left_team_id TEXT NOT NULL,
                    right_team_id TEXT,
                    left_team_name TEXT NOT NULL,
                    right_team_name TEXT NOT NULL DEFAULT '',
                    lane_start INTEGER CHECK (lane_start > 0),
                    status TEXT NOT NULL DEFAULT 'Scheduled' CHECK (status IN (
                        'Scheduled', 'In progress', 'Final', 'Postponed',
                        'Forfeit', 'Cancelled'
                    )),
                    is_position_round INTEGER NOT NULL DEFAULT 0
                        CHECK (is_position_round IN (0, 1)),
                    UNIQUE (round_id, match_number)
                );

                CREATE INDEX IF NOT EXISTS competition_rounds_competition_idx
                    ON competition_rounds(competition_id, round_number);
                CREATE INDEX IF NOT EXISTS competition_matches_round_idx
                    ON competition_matches(round_id, match_number);

                PRAGMA user_version = 4;
                """
            )
            connection.commit()
            self._ensure_schema(connection)
            return
        if version == 2:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(score_change_log)")
            }
            connection.execute("BEGIN IMMEDIATE")
            if "team_id" not in columns:
                connection.execute(
                    """
                    ALTER TABLE score_change_log
                    ADD COLUMN team_id TEXT NOT NULL DEFAULT ''
                    """
                )
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
            self._ensure_schema(connection)
            return
        if version == 1:
            connection.executescript(
                """
                BEGIN IMMEDIATE;

                ALTER TABLE competitions ADD COLUMN games_per_session INTEGER NOT NULL
                    DEFAULT 3 CHECK (games_per_session BETWEEN 1 AND 12);
                ALTER TABLE competitions ADD COLUMN average_rule_name TEXT NOT NULL
                    DEFAULT 'Standard composite';
                ALTER TABLE competitions ADD COLUMN average_minimum_games INTEGER NOT NULL
                    DEFAULT 0 CHECK (average_minimum_games >= 0);
                ALTER TABLE competitions ADD COLUMN average_multiplier TEXT NOT NULL
                    DEFAULT '1';
                ALTER TABLE competitions ADD COLUMN average_add_pins INTEGER NOT NULL
                    DEFAULT 0;
                ALTER TABLE competitions ADD COLUMN average_rounding TEXT NOT NULL
                    DEFAULT 'Nearest whole pin';
                ALTER TABLE competitions ADD COLUMN handicap_base INTEGER NOT NULL
                    DEFAULT 0 CHECK (handicap_base >= 0);
                ALTER TABLE competitions ADD COLUMN handicap_percent TEXT NOT NULL
                    DEFAULT '0';
                ALTER TABLE competitions ADD COLUMN blind_penalty INTEGER NOT NULL
                    DEFAULT 10 CHECK (blind_penalty >= 0);
                ALTER TABLE competitions ADD COLUMN vacancy_score INTEGER NOT NULL
                    DEFAULT 120 CHECK (vacancy_score BETWEEN 0 AND 300);

                CREATE TABLE league_sessions (
                    id TEXT PRIMARY KEY,
                    competition_id TEXT NOT NULL,
                    week_number INTEGER NOT NULL CHECK (week_number > 0),
                    bowled_on TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    games_per_player INTEGER NOT NULL CHECK (games_per_player BETWEEN 1 AND 12),
                    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Final')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (competition_id, week_number)
                );

                CREATE TABLE score_lines (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    registration_id TEXT NOT NULL DEFAULT '',
                    bowler_id TEXT NOT NULL DEFAULT '',
                    team_id TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    roster_role TEXT NOT NULL DEFAULT 'Regular',
                    entering_average INTEGER NOT NULL DEFAULT 0,
                    handicap INTEGER NOT NULL DEFAULT 0,
                    lineup_order INTEGER NOT NULL DEFAULT 0,
                    is_vacancy INTEGER NOT NULL DEFAULT 0 CHECK (is_vacancy IN (0, 1)),
                    UNIQUE (session_id, team_id, lineup_order)
                );

                CREATE TABLE game_scores (
                    id TEXT PRIMARY KEY,
                    score_line_id TEXT NOT NULL,
                    game_number INTEGER NOT NULL CHECK (game_number > 0),
                    status TEXT NOT NULL DEFAULT 'Not entered' CHECK (status IN (
                        'Not entered', 'Bowled', 'Absent', 'Blind', 'Vacancy'
                    )),
                    scratch_score INTEGER CHECK (scratch_score BETWEEN 0 AND 300),
                    pins_counted INTEGER NOT NULL DEFAULT 0 CHECK (pins_counted >= 0),
                    UNIQUE (score_line_id, game_number)
                );

                CREATE TABLE score_change_log (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    score_line_id TEXT NOT NULL DEFAULT '',
                    game_number INTEGER NOT NULL DEFAULT 0,
                    team_id TEXT NOT NULL DEFAULT '',
                    player_name TEXT NOT NULL DEFAULT '',
                    team_name TEXT NOT NULL DEFAULT '',
                    old_status TEXT NOT NULL DEFAULT '',
                    old_scratch_score INTEGER,
                    old_pins_counted INTEGER NOT NULL DEFAULT 0,
                    old_entering_average INTEGER NOT NULL DEFAULT 0,
                    old_handicap INTEGER NOT NULL DEFAULT 0,
                    new_status TEXT NOT NULL DEFAULT '',
                    new_scratch_score INTEGER,
                    new_pins_counted INTEGER NOT NULL DEFAULT 0,
                    new_entering_average INTEGER NOT NULL DEFAULT 0,
                    new_handicap INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );

                CREATE INDEX league_sessions_competition_idx
                    ON league_sessions(competition_id, week_number);
                CREATE INDEX score_lines_session_idx ON score_lines(session_id, team_id);
                CREATE UNIQUE INDEX score_lines_registration_idx
                    ON score_lines(session_id, registration_id)
                    WHERE registration_id <> '';
                CREATE INDEX game_scores_line_idx ON game_scores(score_line_id, game_number);
                CREATE INDEX score_change_log_session_idx
                    ON score_change_log(session_id, changed_at);

                PRAGMA user_version = 3;

                COMMIT;
                """
            )
            connection.commit()
            self._ensure_schema(connection)
            return
        if version != 0:
            raise RegistrationDataError(
                f"Registration database schema {version} is not supported"
            )
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE player_pools (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
            );

            CREATE TABLE bowlers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                membership_id TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE competitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE,
                season TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
                kind TEXT NOT NULL CHECK (kind IN ('League', 'Tournament')),
                created_at TEXT NOT NULL,
                competition_format TEXT NOT NULL DEFAULT 'Round robin',
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                player_pool_id TEXT REFERENCES player_pools(id),
                games_per_session INTEGER NOT NULL DEFAULT 3
                    CHECK (games_per_session BETWEEN 1 AND 12),
                average_rule_name TEXT NOT NULL DEFAULT 'Standard composite',
                average_minimum_games INTEGER NOT NULL DEFAULT 0
                    CHECK (average_minimum_games >= 0),
                average_multiplier TEXT NOT NULL DEFAULT '1',
                average_add_pins INTEGER NOT NULL DEFAULT 0,
                average_rounding TEXT NOT NULL DEFAULT 'Nearest whole pin',
                handicap_base INTEGER NOT NULL DEFAULT 0 CHECK (handicap_base >= 0),
                handicap_percent TEXT NOT NULL DEFAULT '0',
                blind_penalty INTEGER NOT NULL DEFAULT 10 CHECK (blind_penalty >= 0),
                vacancy_score INTEGER NOT NULL DEFAULT 120
                    CHECK (vacancy_score BETWEEN 0 AND 300),
                UNIQUE (kind, name, season)
            );

            CREATE TABLE teams (
                id TEXT PRIMARY KEY,
                competition_id TEXT NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                UNIQUE (competition_id, name)
            );

            CREATE TABLE player_pool_entries (
                pool_id TEXT NOT NULL REFERENCES player_pools(id) ON DELETE CASCADE,
                bowler_id TEXT NOT NULL REFERENCES bowlers(id) ON DELETE CASCADE,
                PRIMARY KEY (pool_id, bowler_id)
            );

            CREATE TABLE registrations (
                id TEXT PRIMARY KEY,
                competition_id TEXT NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
                bowler_id TEXT NOT NULL REFERENCES bowlers(id),
                team_id TEXT REFERENCES teams(id),
                roster_role TEXT NOT NULL DEFAULT 'Regular'
                    CHECK (roster_role IN ('Regular', 'Substitute')),
                verification TEXT NOT NULL DEFAULT 'Not checked'
                    CHECK (verification IN (
                        'Not checked', 'Checking', 'Verified', 'Needs review',
                        'Not found', 'No average', 'Lookup error'
                    )),
                average INTEGER,
                average_year TEXT NOT NULL DEFAULT '',
                games INTEGER,
                note TEXT NOT NULL DEFAULT '',
                withdrawn INTEGER NOT NULL DEFAULT 0 CHECK (withdrawn IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT '',
                UNIQUE (competition_id, bowler_id)
            );

            CREATE INDEX registrations_team_idx ON registrations(team_id);
            CREATE INDEX registrations_competition_idx
                ON registrations(competition_id, withdrawn, roster_role);
            CREATE INDEX teams_competition_idx ON teams(competition_id);

            CREATE TABLE league_sessions (
                id TEXT PRIMARY KEY,
                competition_id TEXT NOT NULL,
                week_number INTEGER NOT NULL CHECK (week_number > 0),
                bowled_on TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL DEFAULT '',
                games_per_player INTEGER NOT NULL CHECK (games_per_player BETWEEN 1 AND 12),
                status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Final')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (competition_id, week_number)
            );

            CREATE TABLE score_lines (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                registration_id TEXT NOT NULL DEFAULT '',
                bowler_id TEXT NOT NULL DEFAULT '',
                team_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team_name TEXT NOT NULL,
                roster_role TEXT NOT NULL DEFAULT 'Regular',
                entering_average INTEGER NOT NULL DEFAULT 0,
                handicap INTEGER NOT NULL DEFAULT 0,
                lineup_order INTEGER NOT NULL DEFAULT 0,
                is_vacancy INTEGER NOT NULL DEFAULT 0 CHECK (is_vacancy IN (0, 1)),
                UNIQUE (session_id, team_id, lineup_order)
            );

            CREATE TABLE game_scores (
                id TEXT PRIMARY KEY,
                score_line_id TEXT NOT NULL,
                game_number INTEGER NOT NULL CHECK (game_number > 0),
                status TEXT NOT NULL DEFAULT 'Not entered' CHECK (status IN (
                    'Not entered', 'Bowled', 'Absent', 'Blind', 'Vacancy'
                )),
                scratch_score INTEGER CHECK (scratch_score BETWEEN 0 AND 300),
                pins_counted INTEGER NOT NULL DEFAULT 0 CHECK (pins_counted >= 0),
                UNIQUE (score_line_id, game_number)
            );

            CREATE TABLE score_change_log (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                score_line_id TEXT NOT NULL DEFAULT '',
                game_number INTEGER NOT NULL DEFAULT 0,
                team_id TEXT NOT NULL DEFAULT '',
                player_name TEXT NOT NULL DEFAULT '',
                team_name TEXT NOT NULL DEFAULT '',
                old_status TEXT NOT NULL DEFAULT '',
                old_scratch_score INTEGER,
                old_pins_counted INTEGER NOT NULL DEFAULT 0,
                old_entering_average INTEGER NOT NULL DEFAULT 0,
                old_handicap INTEGER NOT NULL DEFAULT 0,
                new_status TEXT NOT NULL DEFAULT '',
                new_scratch_score INTEGER,
                new_pins_counted INTEGER NOT NULL DEFAULT 0,
                new_entering_average INTEGER NOT NULL DEFAULT 0,
                new_handicap INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL,
                changed_at TEXT NOT NULL
            );

            CREATE INDEX league_sessions_competition_idx
                ON league_sessions(competition_id, week_number);
            CREATE INDEX score_lines_session_idx ON score_lines(session_id, team_id);
            CREATE UNIQUE INDEX score_lines_registration_idx
                ON score_lines(session_id, registration_id)
                WHERE registration_id <> '';
            CREATE INDEX game_scores_line_idx ON game_scores(score_line_id, game_number);
            CREATE INDEX score_change_log_session_idx
                ON score_change_log(session_id, changed_at);

            CREATE TABLE competition_rounds (
                id TEXT PRIMARY KEY,
                competition_id TEXT NOT NULL,
                round_number INTEGER NOT NULL CHECK (round_number > 0),
                label TEXT NOT NULL DEFAULT '',
                scheduled_on TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'Regular season',
                status TEXT NOT NULL DEFAULT 'Scheduled' CHECK (status IN (
                    'Scheduled', 'In progress', 'Final', 'Postponed', 'Cancelled'
                )),
                created_at TEXT NOT NULL,
                UNIQUE (competition_id, round_number)
            );

            CREATE TABLE competition_matches (
                id TEXT PRIMARY KEY,
                round_id TEXT NOT NULL
                    REFERENCES competition_rounds(id) ON DELETE CASCADE,
                match_number INTEGER NOT NULL CHECK (match_number > 0),
                left_team_id TEXT NOT NULL,
                right_team_id TEXT,
                left_team_name TEXT NOT NULL,
                right_team_name TEXT NOT NULL DEFAULT '',
                lane_start INTEGER CHECK (lane_start > 0),
                status TEXT NOT NULL DEFAULT 'Scheduled' CHECK (status IN (
                    'Scheduled', 'In progress', 'Final', 'Postponed',
                    'Forfeit', 'Cancelled'
                )),
                is_position_round INTEGER NOT NULL DEFAULT 0
                    CHECK (is_position_round IN (0, 1)),
                UNIQUE (round_id, match_number)
            );

            CREATE INDEX competition_rounds_competition_idx
                ON competition_rounds(competition_id, round_number);
            CREATE INDEX competition_matches_round_idx
                ON competition_matches(round_id, match_number);

            PRAGMA user_version = 4;

            COMMIT;
            """
        )
        connection.commit()
        self._ensure_schema(connection)

    def _migrate_legacy_json(self, legacy_path: Path) -> None:
        self._load_legacy_document(legacy_path)
        self._validate_references()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = legacy_path.with_name(
            f"{legacy_path.stem}.pre-sqlite-backup{legacy_path.suffix}"
        )
        if not backup_path.exists():
            shutil.copy2(legacy_path, backup_path)
        temporary_path = self.path.with_name(f".{self.path.name}.migrating")
        if temporary_path.exists():
            temporary_path.unlink()
        destination = self.path
        self.path = temporary_path
        try:
            self.save()
            with closing(self._connect()) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise RegistrationDataError(
                        f"Migrated registration database failed its integrity check: {result}"
                    )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("migrated_from", str(legacy_path)),
                )
                connection.commit()
            temporary_path.replace(destination)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        finally:
            self.path = destination

    def _load_legacy_document(self, legacy_path: Path) -> None:
        try:
            document = json.loads(legacy_path.read_text(encoding="utf-8"))
            if document.get("schemaVersion") not in self.LEGACY_SCHEMA_VERSIONS:
                raise RegistrationDataError(
                    "Legacy registration data uses an unsupported version"
                )
            self.competitions = [
                Competition(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    season=str(item.get("season", "")),
                    kind=CompetitionKind(item["kind"]),
                    created_at=str(item.get("created_at", "")),
                    competition_format=CompetitionFormat(
                        item.get("competition_format", CompetitionFormat.ROUND_ROBIN)
                    ),
                    archived=bool(item.get("archived", False)),
                    player_pool_id=str(item.get("player_pool_id", "")),
                )
                for item in document.get("competitions", [])
            ]
            self.bowlers = [
                BowlerProfile(**item) for item in document.get("bowlers", [])
            ]
            self.player_pools = [
                PlayerPool(**item) for item in document.get("playerPools", [])
            ]
            self.player_pool_entries = [
                PlayerPoolEntry(**item)
                for item in document.get("playerPoolEntries", [])
            ]
            self.teams = [Team(**item) for item in document.get("teams", [])]
            self.registrations = [
                Registration(
                    **{
                        **item,
                        "roster_role": RosterRole(
                            item.get("roster_role", RosterRole.REGULAR)
                        ),
                        "verification": VerificationState(
                            VerificationState.NOT_CHECKED
                            if item.get("verification") == VerificationState.CHECKING
                            else item.get("verification", VerificationState.NOT_CHECKED)
                        ),
                    }
                )
                for item in document.get("registrations", [])
            ]
        except (
            AttributeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            if isinstance(error, RegistrationDataError):
                raise
            raise RegistrationDataError(
                f"Legacy registration data could not be read: {error}"
            ) from error

    def add_competition(
        self,
        name: str,
        season: str,
        kind: CompetitionKind,
        competition_format: CompetitionFormat = CompetitionFormat.ROUND_ROBIN,
    ) -> Competition:
        clean_name = _required(name, "League or tournament name")
        clean_season = season.strip()
        duplicate = next(
            (
                item
                for item in self.competitions
                if item.kind is kind
                and _key(item.name) == _key(clean_name)
                and _key(item.season) == _key(clean_season)
            ),
            None,
        )
        if duplicate:
            raise RegistrationDataError(f"{duplicate.display_name} already exists")
        competition = Competition(
            id=_new_id(),
            name=clean_name,
            season=clean_season,
            kind=kind,
            created_at=_now(),
            competition_format=competition_format,
        )
        self.competitions.append(competition)
        self.save()
        return competition

    def add_team(self, competition_id: str, name: str) -> Team:
        self._competition(competition_id)
        clean_name = _required(name, "Team name")
        if any(
            team.competition_id == competition_id and _key(team.name) == _key(clean_name)
            for team in self.teams
        ):
            raise RegistrationDataError(f"Team {clean_name!r} already exists")
        team = Team(_new_id(), competition_id, clean_name)
        self.teams.append(team)
        self.save()
        return team

    def copy_team_to_competition(
        self,
        source_team_id: str,
        competition_id: str,
        name: str,
        copy_roster: bool = True,
    ) -> tuple[Team, int, int]:
        source_team = self._team(source_team_id)
        self._competition(competition_id)
        clean_name = _required(name, "Team name")
        if source_team.competition_id == competition_id:
            raise RegistrationDataError("Choose a team from another league or tournament")
        if any(
            team.competition_id == competition_id and _key(team.name) == _key(clean_name)
            for team in self.teams
        ):
            raise RegistrationDataError(f"Team {clean_name!r} already exists")

        snapshot = (
            deepcopy(self.teams),
            deepcopy(self.player_pool_entries),
            deepcopy(self.registrations),
        )
        try:
            team = Team(_new_id(), competition_id, clean_name)
            self.teams.append(team)
            copied = 0
            skipped = 0
            if copy_roster:
                source_registrations = [
                    item
                    for item in self.registrations
                    if item.team_id == source_team_id and not item.withdrawn
                ]
                for source_registration in source_registrations:
                    existing = next(
                        (
                            item
                            for item in self.registrations
                            if item.competition_id == competition_id
                            and item.bowler_id == source_registration.bowler_id
                        ),
                        None,
                    )
                    if existing is not None:
                        if existing.team_id or existing.withdrawn:
                            skipped += 1
                            continue
                        existing.team_id = team.id
                        existing.roster_role = source_registration.roster_role
                        copied += 1
                        continue
                    registration = Registration(
                        id=_new_id(),
                        competition_id=competition_id,
                        bowler_id=source_registration.bowler_id,
                        team_id=team.id,
                        roster_role=source_registration.roster_role,
                        created_at=_now(),
                    )
                    self.registrations.append(registration)
                    self._add_registration_to_linked_pool(registration)
                    copied += 1
            self.save()
            return team, copied, skipped
        except Exception:
            self.teams, self.player_pool_entries, self.registrations = snapshot
            raise

    def update_competition(
        self,
        competition_id: str,
        name: str,
        season: str,
        kind: CompetitionKind,
        competition_format: CompetitionFormat | None = None,
    ) -> None:
        competition = self._competition(competition_id)
        clean_name = _required(name, "League or tournament name")
        clean_season = season.strip()
        if any(
            item.id != competition_id
            and item.kind is kind
            and _key(item.name) == _key(clean_name)
            and _key(item.season) == _key(clean_season)
            for item in self.competitions
        ):
            raise RegistrationDataError(
                f"{clean_season + ' • ' if clean_season else ''}{clean_name} already exists"
            )
        competition.name = clean_name
        competition.season = clean_season
        competition.kind = kind
        if competition_format is not None:
            competition.competition_format = competition_format
        self.save()

    def update_competition_scoring_settings(
        self,
        competition_id: str,
        *,
        games_per_session: int,
        average_rule_name: str,
        average_minimum_games: int,
        average_multiplier: Decimal,
        average_add_pins: int,
        average_rounding: AverageRounding,
        handicap_base: int,
        handicap_percent: Decimal,
        blind_penalty: int,
        vacancy_score: int,
    ) -> None:
        competition = self._competition(competition_id)
        if not 1 <= games_per_session <= 12:
            raise RegistrationDataError("Games per night must be between 1 and 12")
        clean_rule_name = _required(average_rule_name, "Average rule name")
        if average_minimum_games < 0:
            raise RegistrationDataError("Minimum games cannot be negative")
        if not average_multiplier.is_finite() or average_multiplier < 0:
            raise RegistrationDataError("Average multiplier must be zero or greater")
        if not -300 <= average_add_pins <= 300:
            raise RegistrationDataError("Average adjustment must be between -300 and 300")
        if not 0 <= handicap_base <= 300:
            raise RegistrationDataError("Handicap base must be between 0 and 300")
        if (
            not handicap_percent.is_finite()
            or handicap_percent < 0
            or handicap_percent > 2
        ):
            raise RegistrationDataError("Handicap percentage must be between 0 and 200")
        if not 0 <= blind_penalty <= 300:
            raise RegistrationDataError("Blind penalty must be between 0 and 300")
        if not 0 <= vacancy_score <= 300:
            raise RegistrationDataError("Vacancy score must be between 0 and 300")

        snapshot = deepcopy(competition)
        try:
            competition.games_per_session = games_per_session
            competition.average_rule_name = clean_rule_name
            competition.average_minimum_games = average_minimum_games
            competition.average_multiplier = average_multiplier
            competition.average_add_pins = average_add_pins
            competition.average_rounding = average_rounding
            competition.handicap_base = handicap_base
            competition.handicap_percent = handicap_percent
            competition.blind_penalty = blind_penalty
            competition.vacancy_score = vacancy_score
            self.save()
        except Exception:
            for field_name in Competition.__dataclass_fields__:
                setattr(competition, field_name, getattr(snapshot, field_name))
            raise

    def competition_average(
        self, competition: Competition, registration: Registration
    ) -> int | None:
        if registration.average is None:
            return None
        rule = AverageRule(
            name=competition.average_rule_name,
            sources=(
                RuleSource(
                    AverageSource.STANDARD_COMPOSITE,
                    minimum_games=competition.average_minimum_games,
                ),
            ),
            multiplier=competition.average_multiplier,
            add_pins=competition.average_add_pins,
            rounding=competition.average_rounding,
        )
        decision = evaluate_average_rule(
            rule,
            [
                AverageCandidate(
                    source=AverageSource.STANDARD_COMPOSITE,
                    average=registration.average,
                    games=registration.games,
                    year=registration.average_year,
                    label=registration.average_year or "Verified standard composite",
                )
            ],
        )
        return decision.average if decision is not None else None

    @staticmethod
    def competition_handicap(competition: Competition, average: int) -> int:
        difference = max(competition.handicap_base - average, 0)
        return int(
            (Decimal(difference) * competition.handicap_percent).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )

    def set_competition_archived(self, competition_id: str, archived: bool) -> None:
        self._competition(competition_id).archived = archived
        self.save()

    def set_competition_player_pool(
        self, competition_id: str, player_pool_id: str
    ) -> None:
        competition = self._competition(competition_id)
        if player_pool_id:
            self._player_pool(player_pool_id)
        competition.player_pool_id = player_pool_id
        if player_pool_id:
            registered_bowler_ids = {
                item.bowler_id
                for item in self.registrations
                if item.competition_id == competition_id
            }
            existing_bowler_ids = {
                item.bowler_id
                for item in self.player_pool_entries
                if item.pool_id == player_pool_id
            }
            self.player_pool_entries.extend(
                PlayerPoolEntry(player_pool_id, bowler_id)
                for bowler_id in registered_bowler_ids - existing_bowler_ids
            )
        self.save()

    def add_player_pool(self, label: str) -> PlayerPool:
        clean_label = _required(label, "Player pool year")
        if any(_key(item.label) == _key(clean_label) for item in self.player_pools):
            raise RegistrationDataError(f"Player pool {clean_label!r} already exists")
        pool = PlayerPool(_new_id(), clean_label, _now())
        self.player_pools.append(pool)
        self.save()
        return pool

    def copy_player_pool(self, source_pool_id: str, new_label: str) -> PlayerPool:
        source = self._player_pool(source_pool_id)
        clean_label = _required(new_label, "Player pool year")
        if any(_key(item.label) == _key(clean_label) for item in self.player_pools):
            raise RegistrationDataError(f"Player pool {clean_label!r} already exists")
        pool = PlayerPool(_new_id(), clean_label, _now())
        self.player_pools.append(pool)
        source_bowler_ids = [
            item.bowler_id
            for item in self.player_pool_entries
            if item.pool_id == source.id
        ]
        self.player_pool_entries.extend(
            PlayerPoolEntry(pool.id, bowler_id) for bowler_id in source_bowler_ids
        )
        self.save()
        return pool

    def pool_bowlers(self, pool_id: str) -> list[BowlerProfile]:
        self._player_pool(pool_id)
        bowler_ids = {
            item.bowler_id
            for item in self.player_pool_entries
            if item.pool_id == pool_id
        }
        return sorted(
            (item for item in self.bowlers if item.id in bowler_ids),
            key=lambda item: _key(item.name),
        )

    def import_players(self, bowlers: list[InputBowler]) -> tuple[int, int]:
        snapshot = deepcopy(self.bowlers)
        added = 0
        reused = 0
        claimed_blank_ids: set[str] = set()
        try:
            for incoming in bowlers:
                clean_name = _required(incoming.name, "Bowler name")
                clean_id = incoming.membership_id.strip()
                matched = None
                if clean_id:
                    matched = next(
                        (
                            item
                            for item in self.bowlers
                            if item.membership_id
                            and _membership_key(item.membership_id)
                            == _membership_key(clean_id)
                        ),
                        None,
                    )
                same_name = [
                    item for item in self.bowlers if _key(item.name) == _key(clean_name)
                ]
                if matched is None:
                    matched = next(
                        (
                            item
                            for item in same_name
                            if not item.membership_id
                            and item.id not in claimed_blank_ids
                        ),
                        None,
                    )
                if matched is None:
                    profile = BowlerProfile(_new_id(), clean_name, clean_id)
                    self.bowlers.append(profile)
                    if not clean_id:
                        claimed_blank_ids.add(profile.id)
                    added += 1
                    continue
                if clean_id and not matched.membership_id:
                    matched.membership_id = clean_id
                elif not matched.membership_id:
                    claimed_blank_ids.add(matched.id)
                reused += 1
            self.save()
        except Exception:
            self.bowlers = snapshot
            raise
        return added, reused

    def add_bowler_to_pool(self, pool_id: str, bowler_id: str) -> None:
        self._player_pool(pool_id)
        self._bowler(bowler_id)
        if not any(
            item.pool_id == pool_id and item.bowler_id == bowler_id
            for item in self.player_pool_entries
        ):
            self.player_pool_entries.append(PlayerPoolEntry(pool_id, bowler_id))
            self.save()

    def remove_bowler_from_pool(self, pool_id: str, bowler_id: str) -> None:
        self._player_pool(pool_id)
        self._bowler(bowler_id)
        self.player_pool_entries = [
            item
            for item in self.player_pool_entries
            if not (item.pool_id == pool_id and item.bowler_id == bowler_id)
        ]
        self.save()

    def list_teams(self, competition_id: str) -> list[Team]:
        return sorted(
            (team for team in self.teams if team.competition_id == competition_id),
            key=lambda item: _key(item.name),
        )

    def rename_team(self, team_id: str, name: str) -> None:
        team = self._team(team_id)
        clean_name = _required(name, "Team name")
        if any(
            item.id != team_id
            and item.competition_id == team.competition_id
            and _key(item.name) == _key(clean_name)
            for item in self.teams
        ):
            raise RegistrationDataError(f"Team {clean_name!r} already exists")
        team.name = clean_name
        self.save()

    def update_bowler_profile(
        self, bowler_id: str, name: str, membership_id: str
    ) -> None:
        bowler = self._bowler(bowler_id)
        clean_name = _required(name, "Bowler name")
        clean_id = membership_id.strip()
        if clean_id and any(
            item.id != bowler_id
            and item.membership_id
            and _membership_key(item.membership_id) == _membership_key(clean_id)
            for item in self.bowlers
        ):
            raise RegistrationDataError(
                f"Member ID {clean_id} already belongs to another player"
            )
        identity_changed = (
            _key(bowler.name) != _key(clean_name)
            or _membership_key(bowler.membership_id) != _membership_key(clean_id)
        )
        bowler.name = clean_name
        bowler.membership_id = clean_id
        if identity_changed:
            for registration in self.registrations:
                if registration.bowler_id == bowler_id:
                    registration.verification = VerificationState.NOT_CHECKED
                    registration.average = None
                    registration.average_year = ""
                    registration.games = None
                    registration.note = "Player identity changed; check the average again"
        self.save()

    def register_bowler(
        self,
        competition_id: str,
        name: str,
        membership_id: str = "",
        team_id: str = "",
        roster_role: RosterRole = RosterRole.REGULAR,
    ) -> Registration:
        snapshot = (
            deepcopy(self.bowlers),
            deepcopy(self.player_pool_entries),
            deepcopy(self.registrations),
        )
        try:
            registration = self._register_bowler(
                competition_id, name, membership_id, team_id, roster_role
            )
            self.save()
            return registration
        except Exception:
            self.bowlers, self.player_pool_entries, self.registrations = snapshot
            raise

    def register_existing_bowler(
        self,
        competition_id: str,
        bowler_id: str,
        team_id: str = "",
        roster_role: RosterRole = RosterRole.REGULAR,
    ) -> Registration:
        bowler = self._bowler(bowler_id)
        return self.register_bowler(
            competition_id,
            bowler.name,
            bowler.membership_id,
            team_id,
            roster_role,
        )

    def register_bowler_many(
        self,
        name: str,
        membership_id: str,
        targets: list[RegistrationTarget],
    ) -> list[Registration]:
        if not targets:
            raise RegistrationDataError("Choose at least one league or tournament")
        competition_ids = [target.competition_id for target in targets]
        if len(competition_ids) != len(set(competition_ids)):
            raise RegistrationDataError("Choose each league or tournament only once")
        snapshot = (
            deepcopy(self.bowlers),
            deepcopy(self.player_pool_entries),
            deepcopy(self.teams),
            deepcopy(self.registrations),
        )
        try:
            registrations = []
            for target in targets:
                competition = self._competition(target.competition_id)
                if competition.archived:
                    raise RegistrationDataError(
                        f"{competition.display_name} is archived"
                    )
                if target.team_id and target.new_team_name:
                    raise RegistrationDataError(
                        "Choose an existing team or create a new team, not both"
                    )
                team_id = target.team_id
                if target.new_team_name:
                    clean_team_name = _required(target.new_team_name, "Team name")
                    existing = next(
                        (
                            team
                            for team in self.list_teams(competition.id)
                            if _key(team.name) == _key(clean_team_name)
                        ),
                        None,
                    )
                    if existing is not None:
                        team_id = existing.id
                    else:
                        team = Team(_new_id(), competition.id, clean_team_name)
                        self.teams.append(team)
                        team_id = team.id
                registrations.append(
                    self._register_bowler(
                        competition.id,
                        name,
                        membership_id,
                        team_id,
                        target.roster_role,
                    )
                )
            self.save()
            return registrations
        except Exception:
            (
                self.bowlers,
                self.player_pool_entries,
                self.teams,
                self.registrations,
            ) = snapshot
            raise

    def register_team(
        self,
        competition_id: str,
        team_name: str,
        bowlers: list[InputBowler],
    ) -> tuple[Team, list[Registration]]:
        if not bowlers:
            raise RegistrationDataError("Enter at least one bowler")
        snapshot = (
            deepcopy(self.bowlers),
            deepcopy(self.player_pool_entries),
            deepcopy(self.teams),
            deepcopy(self.registrations),
        )
        try:
            existing = next(
                (
                    team
                    for team in self.list_teams(competition_id)
                    if _key(team.name) == _key(team_name)
                ),
                None,
            )
            team = existing or Team(
                _new_id(), competition_id, _required(team_name, "Team name")
            )
            if existing is None:
                self.teams.append(team)
            registrations = [
                self._register_bowler(
                    competition_id,
                    bowler.name,
                    bowler.membership_id,
                    team.id,
                    RosterRole.REGULAR,
                )
                for bowler in bowlers
            ]
            self.save()
            return team, registrations
        except Exception:
            (
                self.bowlers,
                self.player_pool_entries,
                self.teams,
                self.registrations,
            ) = snapshot
            raise

    def registration_views(self, competition_id: str) -> list[RegistrationView]:
        bowler_by_id = {bowler.id: bowler for bowler in self.bowlers}
        team_by_id = {team.id: team for team in self.teams}
        return sorted(
            (
                RegistrationView(
                    registration,
                    bowler_by_id[registration.bowler_id],
                    team_by_id.get(registration.team_id),
                )
                for registration in self.registrations
                if registration.competition_id == competition_id
            ),
            key=lambda item: (
                item.registration.withdrawn,
                _key(item.team.name) if item.team else "zzzz",
                _key(item.bowler.name),
            ),
        )

    def mark_checking(self, registration_id: str) -> None:
        self.mark_checking_many([registration_id])

    def mark_checking_many(self, registration_ids: list[str]) -> None:
        for registration_id in registration_ids:
            registration = self._registration(registration_id)
            registration.verification = VerificationState.CHECKING
            registration.note = "Waiting for BOWL.com"
        self.save()

    def mark_lookup_error(self, registration_id: str, note: str) -> None:
        snapshot = deepcopy(self.registrations)
        try:
            registration = self._registration(registration_id)
            registration.verification = VerificationState.ERROR
            registration.average = None
            registration.average_year = ""
            registration.games = None
            registration.note = note.strip() or "Lookup result could not be saved"
            self.save()
        except Exception:
            self.registrations = snapshot
            raise

    def apply_lookup_result(self, registration_id: str, result: LookupResult) -> None:
        snapshot = (
            deepcopy(self.bowlers),
            deepcopy(self.player_pool_entries),
            deepcopy(self.registrations),
        )
        try:
            registration = self._registration(registration_id)
            bowler = self._bowler(registration.bowler_id)
            if result.membership_id:
                self._apply_result_identity(
                    registration, bowler, result.membership_id.strip()
                )
            registration.average = result.average
            registration.average_year = result.year
            registration.games = result.games
            registration.note = result.note
            if result.status is LookupStatus.FOUND or result.confirmed_inactive:
                registration.verification = VerificationState.VERIFIED
            elif result.status is LookupStatus.MULTIPLE_MATCHES:
                registration.verification = VerificationState.NEEDS_REVIEW
            elif result.status is LookupStatus.NOT_FOUND:
                registration.verification = VerificationState.NOT_FOUND
            elif result.status is LookupStatus.NO_AVERAGE:
                registration.verification = VerificationState.NO_AVERAGE
            else:
                registration.verification = VerificationState.ERROR
            self.save()
        except Exception:
            self.bowlers, self.player_pool_entries, self.registrations = snapshot
            raise

    def _apply_result_identity(
        self,
        registration: Registration,
        current_bowler: BowlerProfile,
        membership_id: str,
    ) -> None:
        target = next(
            (
                bowler
                for bowler in self.bowlers
                if bowler.id != current_bowler.id
                and bowler.membership_id
                and _membership_key(bowler.membership_id)
                == _membership_key(membership_id)
            ),
            None,
        )
        if target is None:
            current_bowler.membership_id = membership_id
            return
        if any(
            item.id != registration.id
            and item.competition_id == registration.competition_id
            and item.bowler_id == target.id
            for item in self.registrations
        ):
            raise RegistrationDataError(
                f"Member ID {membership_id} is already registered in this competition"
            )

        current_registrations = [
            item for item in self.registrations if item.bowler_id == current_bowler.id
        ]
        target_competition_ids = {
            item.competition_id
            for item in self.registrations
            if item.bowler_id == target.id
        }
        can_merge_profile = not any(
            item.competition_id in target_competition_ids
            for item in current_registrations
        )
        if can_merge_profile:
            for item in current_registrations:
                item.bowler_id = target.id
            for pool_entry in self.player_pool_entries:
                if pool_entry.bowler_id == current_bowler.id:
                    pool_entry.bowler_id = target.id
            self._deduplicate_pool_entries()
            self.bowlers.remove(current_bowler)
            return

        registration.bowler_id = target.id
        competition = self._competition(registration.competition_id)
        if competition.player_pool_id and not any(
            item.pool_id == competition.player_pool_id and item.bowler_id == target.id
            for item in self.player_pool_entries
        ):
            self.player_pool_entries.append(
                PlayerPoolEntry(competition.player_pool_id, target.id)
            )

    def assign_team(self, registration_id: str, team_id: str) -> None:
        registration = self._registration(registration_id)
        self.assign_registration(
            registration_id, team_id, registration.roster_role
        )

    def assign_registration(
        self,
        registration_id: str,
        team_id: str,
        roster_role: RosterRole,
    ) -> None:
        registration = self._registration(registration_id)
        if team_id:
            team = self._team(team_id)
            if team.competition_id != registration.competition_id:
                raise RegistrationDataError("That team belongs to another competition")
        registration.team_id = team_id
        registration.roster_role = roster_role
        self.save()

    def update_registration(
        self,
        registration_id: str,
        name: str,
        membership_id: str,
        team_id: str,
        roster_role: RosterRole | None = None,
    ) -> None:
        registration = self._registration(registration_id)
        current_bowler = self._bowler(registration.bowler_id)
        clean_name = _required(name, "Bowler name")
        clean_id = membership_id.strip()
        if team_id:
            team = self._team(team_id)
            if team.competition_id != registration.competition_id:
                raise RegistrationDataError("That team belongs to another competition")

        target = None
        if clean_id:
            target = next(
                (
                    bowler
                    for bowler in self.bowlers
                    if bowler.id != current_bowler.id
                    and bowler.membership_id
                    and _membership_key(bowler.membership_id)
                    == _membership_key(clean_id)
                ),
                None,
            )
        if target is not None:
            if any(
                item.id != registration.id
                and item.competition_id == registration.competition_id
                and item.bowler_id == target.id
                for item in self.registrations
            ):
                raise RegistrationDataError(
                    f"Member ID {clean_id} is already registered in this competition"
                )
            registration.bowler_id = target.id
            self._add_registration_to_linked_pool(registration)
            target.name = clean_name
            registration.verification = VerificationState.NOT_CHECKED
            registration.average = None
            registration.average_year = ""
            registration.games = None
            registration.note = "Identity changed; check the average again"
            if not any(
                item.bowler_id == current_bowler.id for item in self.registrations
            ):
                for pool_entry in self.player_pool_entries:
                    if pool_entry.bowler_id == current_bowler.id:
                        pool_entry.bowler_id = target.id
                self._deduplicate_pool_entries()
                self.bowlers.remove(current_bowler)
        else:
            identity_changed = (
                _key(current_bowler.name) != _key(clean_name)
                or _membership_key(current_bowler.membership_id)
                != _membership_key(clean_id)
            )
            current_bowler.name = clean_name
            current_bowler.membership_id = clean_id
            if identity_changed:
                registration.verification = VerificationState.NOT_CHECKED
                registration.average = None
                registration.average_year = ""
                registration.games = None
                registration.note = "Identity changed; check the average again"
        registration.team_id = team_id
        if roster_role is not None:
            registration.roster_role = roster_role
        self.save()

    def set_withdrawn(self, registration_id: str, withdrawn: bool) -> None:
        self._registration(registration_id).withdrawn = withdrawn
        self.save()

    def _register_bowler(
        self,
        competition_id: str,
        name: str,
        membership_id: str,
        team_id: str,
        roster_role: RosterRole,
    ) -> Registration:
        self._competition(competition_id)
        clean_name = _required(name, "Bowler name")
        clean_id = membership_id.strip()
        if team_id:
            team = self._team(team_id)
            if team.competition_id != competition_id:
                raise RegistrationDataError("That team belongs to another competition")
        bowler = self._find_bowler(clean_name, clean_id)
        if bowler is None:
            bowler = BowlerProfile(_new_id(), clean_name, clean_id)
            self.bowlers.append(bowler)
        elif clean_id and not bowler.membership_id:
            bowler.membership_id = clean_id
        if any(
            item.competition_id == competition_id and item.bowler_id == bowler.id
            for item in self.registrations
        ):
            raise RegistrationDataError(f"{bowler.name} is already registered")
        registration = Registration(
            id=_new_id(),
            competition_id=competition_id,
            bowler_id=bowler.id,
            team_id=team_id,
            roster_role=roster_role,
            created_at=_now(),
        )
        self.registrations.append(registration)
        self._add_registration_to_linked_pool(registration)
        return registration

    def _add_registration_to_linked_pool(self, registration: Registration) -> None:
        competition = self._competition(registration.competition_id)
        if competition.player_pool_id and not any(
            item.pool_id == competition.player_pool_id
            and item.bowler_id == registration.bowler_id
            for item in self.player_pool_entries
        ):
            self.player_pool_entries.append(
                PlayerPoolEntry(competition.player_pool_id, registration.bowler_id)
            )

    def _find_bowler(self, name: str, membership_id: str) -> BowlerProfile | None:
        if membership_id:
            member_key = _membership_key(membership_id)
            member_match = next(
                (
                    bowler
                    for bowler in self.bowlers
                    if bowler.membership_id
                    and _membership_key(bowler.membership_id) == member_key
                ),
                None,
            )
            if member_match:
                return member_match
            # Two people may share a name. A different known ID must create a new profile.
            named = [bowler for bowler in self.bowlers if _key(bowler.name) == _key(name)]
            return next((bowler for bowler in named if not bowler.membership_id), None)
        named = [bowler for bowler in self.bowlers if _key(bowler.name) == _key(name)]
        return named[0] if len(named) == 1 else None

    def _validate_references(self) -> None:
        competition_ids = {item.id for item in self.competitions}
        bowler_ids = {item.id for item in self.bowlers}
        player_pool_ids = {item.id for item in self.player_pools}
        if any(
            item.player_pool_id and item.player_pool_id not in player_pool_ids
            for item in self.competitions
        ):
            raise RegistrationDataError("Registration data contains an unknown player pool")
        if any(
            item.pool_id not in player_pool_ids or item.bowler_id not in bowler_ids
            for item in self.player_pool_entries
        ):
            raise RegistrationDataError("Registration data contains an orphaned player pool entry")
        team_ids = {item.id for item in self.teams}
        if any(team.competition_id not in competition_ids for team in self.teams):
            raise RegistrationDataError("Registration data contains an orphaned team")
        for registration in self.registrations:
            if (
                registration.competition_id not in competition_ids
                or registration.bowler_id not in bowler_ids
                or registration.team_id
                and registration.team_id not in team_ids
            ):
                raise RegistrationDataError("Registration data contains an orphaned entry")
            if registration.team_id:
                team = next(item for item in self.teams if item.id == registration.team_id)
                if team.competition_id != registration.competition_id:
                    raise RegistrationDataError(
                        "Registration data assigns a player to another competition's team"
                    )

    def _competition(self, item_id: str) -> Competition:
        return _find(self.competitions, item_id, "competition")

    def _bowler(self, item_id: str) -> BowlerProfile:
        return _find(self.bowlers, item_id, "bowler")

    def _team(self, item_id: str) -> Team:
        return _find(self.teams, item_id, "team")

    def _player_pool(self, item_id: str) -> PlayerPool:
        return _find(self.player_pools, item_id, "player pool")

    def _registration(self, item_id: str) -> Registration:
        return _find(self.registrations, item_id, "registration")

    def _deduplicate_pool_entries(self) -> None:
        seen: set[tuple[str, str]] = set()
        unique: list[PlayerPoolEntry] = []
        for item in self.player_pool_entries:
            key = (item.pool_id, item.bowler_id)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        self.player_pool_entries = unique


def _find(items: list, item_id: str, label: str):
    item = next((candidate for candidate in items if candidate.id == item_id), None)
    if item is None:
        raise RegistrationDataError(f"Unknown {label}")
    return item


def _required(value: str, label: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise RegistrationDataError(f"{label} is required")
    return cleaned


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _membership_key(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", value.casefold())


def _new_id() -> str:
    return uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat()
