"""Permanent storage. Connections belong to one operation, never to a GUI worker."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from os import environ
from pathlib import Path

from usbc_average_lookup.models import CompositeAverage, InputBowler, LeagueAverage, Member
from usbc_average_lookup.services.bowl_api import _split_membership_id
from usbc_average_lookup.services.sanitize import sanitize

SCHEMA_VERSION = 4

MIGRATIONS = (
    (
        """CREATE TABLE bowlers (
            id INTEGER PRIMARY KEY, membership_id TEXT UNIQUE,
            display_name TEXT NOT NULL, name_key TEXT NOT NULL,
            member_id TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            middle_initial TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '',
            gender TEXT NOT NULL DEFAULT '', active INTEGER,
            association TEXT NOT NULL DEFAULT '', association_state TEXT NOT NULL DEFAULT '',
            membership_from TEXT NOT NULL DEFAULT '', membership_thru TEXT NOT NULL DEFAULT '',
            product TEXT NOT NULL DEFAULT '', flags_json TEXT NOT NULL DEFAULT '{}',
            member_json TEXT NOT NULL DEFAULT '{}', candidates_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL, refreshed_at TEXT, attempted_at TEXT,
            status TEXT NOT NULL DEFAULT 'Not refreshed', note TEXT NOT NULL DEFAULT ''
        )""",
        "CREATE INDEX bowlers_name ON bowlers(name_key)",
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        """CREATE TABLE aliases (bowler_id INTEGER NOT NULL REFERENCES bowlers(id),
            name_key TEXT NOT NULL, PRIMARY KEY(bowler_id, name_key))""",
    ),
    (
        """CREATE TABLE averages (
            id INTEGER PRIMARY KEY, bowler_id INTEGER NOT NULL REFERENCES bowlers(id),
            year TEXT NOT NULL, sport INTEGER NOT NULL, challenge INTEGER NOT NULL,
            hand TEXT NOT NULL, games INTEGER NOT NULL, average INTEGER NOT NULL,
            raw_json TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            UNIQUE(bowler_id, year, sport, challenge, hand)
        )""",
        """CREATE TABLE average_history (
            id INTEGER PRIMARY KEY, bowler_id INTEGER NOT NULL REFERENCES bowlers(id),
            year TEXT NOT NULL, sport INTEGER NOT NULL, challenge INTEGER NOT NULL,
            hand TEXT NOT NULL, games INTEGER NOT NULL, average INTEGER NOT NULL,
            raw_json TEXT NOT NULL, observed_at TEXT NOT NULL
        )""",
        "CREATE INDEX average_history_bowler ON average_history(bowler_id)",
        """CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY, bowler_id INTEGER NOT NULL REFERENCES bowlers(id),
            endpoint TEXT NOT NULL, digest TEXT NOT NULL, payload_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            UNIQUE(bowler_id, endpoint, digest)
        )""",
    ),
    (
        """CREATE TABLE league_averages (
            id INTEGER PRIMARY KEY, bowler_id INTEGER NOT NULL REFERENCES bowlers(id),
            identity_key TEXT NOT NULL, digest TEXT NOT NULL, normalized_json TEXT NOT NULL,
            current INTEGER NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            UNIQUE(bowler_id,identity_key,digest)
        )""",
        "CREATE INDEX league_averages_bowler ON league_averages(bowler_id,current)",
    ),
    (
        "ALTER TABLE bowlers ADD COLUMN search_state TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE bowlers ADD COLUMN search_zip TEXT NOT NULL DEFAULT ''",
    ),
)


def default_database_path() -> Path:
    return Path(environ.get("LOCALAPPDATA", Path.home())) / "Average Assistant" / "bowlers.sqlite3"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def encode(value: object) -> str:
    return json.dumps(sanitize(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ImportResult:
    added: tuple[int, ...]
    reused: tuple[int, ...]
    conflicts: tuple[InputBowler, ...]


class BowlerDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("This database needs a newer version of Average Assistant")
            for index in range(version, SCHEMA_VERSION):
                for statement in MIGRATIONS[index]:
                    db.execute(statement)
                db.execute(f"PRAGMA user_version={index + 1}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, bowler_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM bowlers WHERE id=?", (bowler_id,)).fetchone()
        if row is None:
            raise ValueError("The bowler no longer exists")
        return dict(row)

    def list_bowlers(self, query: str = "", status: str = "All") -> list[dict]:
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM bowlers ORDER BY name_key, id")]
        terms = name_key(query).split()
        return [
            row
            for row in rows
            if all(
                term
                in name_key(
                    " ".join(
                        str(row[key] or "")
                        for key in (
                            "display_name",
                            "membership_id",
                            "association",
                            "association_state",
                            "status",
                        )
                    )
                )
                for term in terms
            )
            and (
                status == "All"
                or (status == "Active" and row["active"] == 1)
                or (status == "Inactive" and row["active"] == 0)
                or (status == "Needs attention" and row["status"] != "Refreshed")
            )
        ]

    def import_bowlers(
        self, bowlers: Iterable[InputBowler], *, allow_same_name: bool = False
    ) -> ImportResult:
        added, reused, conflicts = [], [], []
        # Validate before the transaction: a malformed row never causes partial import.
        inputs = list(bowlers)
        for bowler in inputs:
            if not bowler.name.strip() and not bowler.membership_id.strip():
                raise ValueError("Enter a name or USBC ID")
            _split_membership_id(bowler.membership_id.strip())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for bowler in inputs:
                membership_id = bowler.membership_id.strip() or None
                key = name_key(bowler.name)
                row = (
                    db.execute(
                        "SELECT id FROM bowlers WHERE membership_id=?", (membership_id,)
                    ).fetchone()
                    if membership_id
                    else None
                )
                if row is None and not membership_id and not allow_same_name:
                    matches = db.execute(
                        "SELECT DISTINCT b.id, b.membership_id FROM bowlers b "
                        "LEFT JOIN aliases a ON a.bowler_id=b.id "
                        "WHERE b.name_key=? OR a.name_key=?",
                        (key, key),
                    ).fetchall()
                    if len(matches) == 1 and not matches[0]["membership_id"]:
                        row = matches[0]
                    elif matches:
                        conflicts.append(bowler)
                        continue
                if row:
                    reused.append(row["id"])
                    if key:
                        db.execute("INSERT OR IGNORE INTO aliases VALUES (?,?)", (row["id"], key))
                    continue
                display = " ".join(bowler.name.split()) or membership_id
                parts = bowler.name.split()
                cursor = db.execute(
                    "INSERT INTO bowlers (membership_id, display_name, name_key, first_name, "
                    "middle_initial, last_name, created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        membership_id,
                        display,
                        name_key(display),
                        parts[0] if parts else "",
                        parts[1][:1] if len(parts) > 2 else "",
                        parts[-1] if len(parts) > 1 else "",
                        now(),
                    ),
                )
                added.append(cursor.lastrowid)
                db.execute("INSERT INTO aliases VALUES (?,?)", (cursor.lastrowid, key))
        return ImportResult(tuple(added), tuple(reused), tuple(conflicts))

    def find_name_matches(self, name: str) -> list[dict]:
        """Use the same exact saved-name/alias matching as import duplicate detection."""
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT DISTINCT b.* FROM bowlers b LEFT JOIN aliases a ON a.bowler_id=b.id "
                    "WHERE b.name_key=? OR a.name_key=? ORDER BY b.id",
                    (name_key(name), name_key(name)),
                )
            ]

    def delete_bowlers(self, bowler_ids: Iterable[int]) -> int:
        """Remove selected local records and their dependent data in one transaction."""
        ids = list(dict.fromkeys(bowler_ids))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for bowler_id in ids:
                if db.execute("SELECT id FROM bowlers WHERE id=?", (bowler_id,)).fetchone() is None:
                    raise ValueError("A selected bowler no longer exists; refresh the list")
            for bowler_id in ids:
                for table in (
                    "aliases",
                    "averages",
                    "average_history",
                    "snapshots",
                    "league_averages",
                ):
                    db.execute(f"DELETE FROM {table} WHERE bowler_id=?", (bowler_id,))
                db.execute("DELETE FROM bowlers WHERE id=?", (bowler_id,))
        return len(ids)

    def set_identity(
        self,
        bowler_id: int,
        name: str,
        membership_id: str,
        *,
        search_state: str = "",
        search_zip: str = "",
    ) -> None:
        """Correct an unresolved identity; never move history to a different person."""
        membership_id = membership_id.strip()
        _split_membership_id(membership_id)
        if not name.strip() and not membership_id:
            raise ValueError("Enter a name or USBC ID")
        search_state = search_state.strip().upper()
        search_zip = search_zip.strip()
        if search_state and (
            len(search_state) != 2 or not search_state.isascii() or not search_state.isalpha()
        ):
            raise ValueError("Enter a two-letter state abbreviation, such as TX")
        if search_zip and (
            len(search_zip) != 5 or not search_zip.isascii() or not search_zip.isdigit()
        ):
            raise ValueError("Enter a five-digit ZIP code")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM bowlers WHERE id=?", (bowler_id,)).fetchone()
            if row is None:
                raise ValueError("The bowler no longer exists")
            if row["refreshed_at"] and membership_id != row["membership_id"]:
                raise ValueError("Add a separate bowler to use a different USBC ID")
            other = db.execute(
                "SELECT id FROM bowlers WHERE membership_id=? AND id<>?", (membership_id, bowler_id)
            ).fetchone()
            if other:
                raise ValueError("That USBC ID is already saved; use the existing bowler")
            display = " ".join(name.split()) or membership_id
            parts = name.split()
            if display != row["display_name"] or not row["refreshed_at"]:
                first, middle, last = (
                    parts[0] if parts else "",
                    parts[1][:1] if len(parts) > 2 else "",
                    parts[-1] if len(parts) > 1 else "",
                )
            else:
                first, middle, last = row["first_name"], row["middle_initial"], row["last_name"]
            db.execute(
                "UPDATE bowlers SET display_name=?,name_key=?,membership_id=?, "
                "first_name=?,middle_initial=?,last_name=?, "
                "search_state=?,search_zip=?,candidates_json='[]',"
                "status='Not refreshed',note='' WHERE id=?",
                (
                    display,
                    name_key(display),
                    membership_id or None,
                    first,
                    middle,
                    last,
                    search_state,
                    search_zip,
                    bowler_id,
                ),
            )
            db.execute("INSERT OR IGNORE INTO aliases VALUES (?,?)", (bowler_id, name_key(display)))

    def save_refresh(
        self,
        bowler_id: int,
        member: Member,
        averages: Iterable[CompositeAverage],
        snapshots: dict[str, object],
        note: str = "",
        league_averages: Iterable[LeagueAverage] = (),
    ) -> int:
        stamp = now()
        membership_id = f"{member.prefix}-{member.suffix}"
        _split_membership_id(membership_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            original = db.execute("SELECT * FROM bowlers WHERE id=?", (bowler_id,)).fetchone()
            if original is None:
                raise ValueError("The bowler no longer exists")
            if original["membership_id"] and original["membership_id"] != membership_id:
                raise ValueError("BOWL.com returned a different USBC ID; nothing was changed")
            duplicate = db.execute(
                "SELECT id FROM bowlers WHERE membership_id=? AND id<>?", (membership_id, bowler_id)
            ).fetchone()
            # An unresolved imported name can resolve to a person already in the database.
            # Keep the canonical record and move its input aliases; no history is discarded.
            if duplicate:
                canonical = duplicate["id"]
                if original["refreshed_at"]:
                    raise ValueError("Duplicate verified identity requires manual review")
                db.execute(
                    "INSERT OR IGNORE INTO aliases SELECT ?,name_key FROM aliases "
                    "WHERE bowler_id=?",
                    (canonical, bowler_id),
                )
                db.execute("DELETE FROM aliases WHERE bowler_id=?", (bowler_id,))
                db.execute("DELETE FROM snapshots WHERE bowler_id=?", (bowler_id,))
                db.execute("DELETE FROM bowlers WHERE id=?", (bowler_id,))
                bowler_id = canonical
            db.execute(
                "UPDATE bowlers SET membership_id=?,display_name=?,name_key=?,member_id=?, "
                "first_name=?,middle_initial=?,last_name=?,gender=?,active=?,association=?, "
                "association_state=?,membership_from=?,membership_thru=?,product=?,flags_json=?, "
                "member_json=?,refreshed_at=?,attempted_at=?,status='Refreshed',note=?, "
                "candidates_json='[]' WHERE id=?",
                (
                    membership_id,
                    member.display_name,
                    name_key(member.display_name),
                    member.member_id,
                    member.first_name,
                    member.middle_initial,
                    member.last_name,
                    member.gender,
                    member.active,
                    member.association,
                    member.association_state,
                    member.membership_from,
                    member.membership_thru,
                    member.product,
                    encode(member.flags),
                    encode(asdict(member)),
                    stamp,
                    stamp,
                    str(sanitize(note)),
                    bowler_id,
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO aliases VALUES (?,?)",
                (bowler_id, name_key(member.display_name)),
            )
            for average in averages:
                key = (bowler_id, average.year, average.sport, average.challenge, average.hand)
                values = (average.games, average.average, encode(average.raw))
                previous = db.execute(
                    "SELECT games,average,raw_json FROM averages WHERE bowler_id=? "
                    "AND year=? AND sport=? AND challenge=? AND hand=?",
                    key,
                ).fetchone()
                if previous is None or tuple(previous) != values:
                    db.execute(
                        "INSERT INTO average_history (bowler_id,year,sport,challenge,hand,"
                        "games,average,raw_json,observed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (*key, *values, stamp),
                    )
                db.execute(
                    "INSERT INTO averages (bowler_id,year,sport,challenge,hand,games,average,"
                    "raw_json,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(bowler_id,year,sport,challenge,hand) DO UPDATE SET "
                    "games=excluded.games,average=excluded.average,raw_json=excluded.raw_json,"
                    "last_seen_at=excluded.last_seen_at",
                    (*key, *values, stamp, stamp),
                )
            for average in league_averages:
                normalized = asdict(average)
                identity = encode(
                    [
                        normalized[key]
                        for key in (
                            "league_id",
                            "year",
                            "season",
                            "hand",
                            "sport",
                            "challenge",
                            "string_pin",
                            "pattern",
                            "roll_and_grow",
                            "bumper",
                        )
                    ]
                )
                encoded = encode(normalized)
                db.execute(
                    "UPDATE league_averages SET current=0 WHERE bowler_id=? AND identity_key=?",
                    (bowler_id, identity),
                )
                db.execute(
                    "INSERT INTO league_averages (bowler_id,identity_key,digest,"
                    "normalized_json,current,first_seen_at,last_seen_at) "
                    "VALUES (?,?,?,?,1,?,?) ON CONFLICT(bowler_id,identity_key,digest) "
                    "DO UPDATE SET current=1,last_seen_at=excluded.last_seen_at",
                    (
                        bowler_id,
                        identity,
                        sha256(encoded.encode()).hexdigest(),
                        encoded,
                        stamp,
                        stamp,
                    ),
                )
            for endpoint, payload in snapshots.items():
                encoded = encode(payload)
                db.execute(
                    "INSERT INTO snapshots (bowler_id,endpoint,digest,payload_json,first_seen_at,"
                    "last_seen_at) VALUES (?,?,?,?,?,?) ON CONFLICT(bowler_id,endpoint,digest) "
                    "DO UPDATE SET last_seen_at=excluded.last_seen_at",
                    (
                        bowler_id,
                        endpoint,
                        sha256(encoded.encode()).hexdigest(),
                        encoded,
                        stamp,
                        stamp,
                    ),
                )
        return bowler_id

    def save_status(
        self, bowler_id: int, status: str, note: str, candidates: Iterable[Member] = ()
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE bowlers SET status=?,note=?,attempted_at=?,candidates_json=? WHERE id=?",
                (
                    status,
                    str(sanitize(note)),
                    now(),
                    encode([asdict(m) for m in candidates]),
                    bowler_id,
                ),
            )

    def averages(self, bowler_id: int, *, history: bool = False) -> list[dict]:
        table = "average_history" if history else "averages"
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM {table} WHERE bowler_id=? ORDER BY year DESC,id DESC",
                    (bowler_id,),
                )
            ]

    def snapshots(self, bowler_id: int) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM snapshots WHERE bowler_id=? ORDER BY id DESC", (bowler_id,)
                )
            ]

    def league_averages(self, bowler_id: int, *, history: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM league_averages WHERE bowler_id=? "
                + ("" if history else "AND current=1 ")
                + "ORDER BY id DESC",
                (bowler_id,),
            ).fetchall()
        return [{**dict(row), **json.loads(row["normalized_json"])} for row in rows]

    def setting(self, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def validate_destination(self, destination: Path) -> None:
        target = destination.resolve()
        for protected in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
            if target == protected.resolve() or (
                target.exists() and protected.exists() and target.samefile(protected)
            ):
                raise ValueError(
                    "Choose a separate file; the live bowler database cannot be overwritten"
                )

    def backup(self, destination: Path) -> None:
        self.validate_destination(destination)
        with self.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
