from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from usbc_average_lookup.services.registration import RegistrationDataError, RegistrationStore
from usbc_average_lookup.services.scheduling import MatchStatus, RoundStatus, ScheduleStore
from usbc_average_lookup.services.scoring import GameStatus, ScoringStore, SessionStatus


@dataclass(frozen=True)
class StandingRules:
    comparison: str = "Handicap"
    game_points: str = "1"
    series_points: str = "1"
    ties: str = "Split points"
    ranking: str = "Series wins"
    tiebreaker: str = "None"

    def validate(self) -> None:
        for value, choices in (
            (self.comparison, ("Scratch", "Handicap")),
            (self.ties, ("Split points", "No points")),
            (self.ranking, ("Series wins", "Points", "Game wins")),
            (self.tiebreaker, ("None", "Scratch pins", "Handicap pins")),
        ):
            if value not in choices:
                raise RegistrationDataError("Unknown standings rule")
        for value in (self.game_points, self.series_points):
            try:
                number = Decimal(value)
            except InvalidOperation as error:
                raise RegistrationDataError("Points must be numbers") from error
            if not number.is_finite() or not 0 <= number <= 100:
                raise RegistrationDataError("Points must be between 0 and 100")

    def encode(self) -> str:
        self.validate()
        return json.dumps(asdict(self), sort_keys=True)


@dataclass
class TeamStanding:
    team_id: str
    team_name: str
    played: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    game_wins: int = 0
    game_losses: int = 0
    game_ties: int = 0
    points: Decimal = Decimal(0)
    scratch_pins: int = 0
    handicap_pins: int = 0
    rank: int = 0


@dataclass(frozen=True)
class MatchResult:
    match_id: str
    matchup: str
    status: str
    left_points: Decimal = Decimal(0)
    right_points: Decimal = Decimal(0)
    left_total: int | None = None
    right_total: int | None = None


class StandingsStore:
    """Derived results only; links freeze the scoring rules used for each round."""

    def __init__(self, registrations: RegistrationStore) -> None:
        self.registrations = registrations
        self.schedules = ScheduleStore(registrations)
        self.scores = ScoringStore(registrations)

    def rules(self, competition_id: str) -> StandingRules:
        self.registrations._competition(competition_id)
        with closing(self.registrations._connect()) as connection:
            row = connection.execute(
                "SELECT rules_json FROM standing_rules WHERE competition_id = ?",
                (competition_id,),
            ).fetchone()
        return StandingRules(**json.loads(row[0])) if row else StandingRules()

    def save_rules(self, competition_id: str, rules: StandingRules) -> None:
        self.registrations._competition(competition_id)
        encoded = rules.encode()
        with closing(self.registrations._connect()) as connection:
            connection.execute(
                "INSERT INTO standing_rules VALUES (?, ?) ON CONFLICT(competition_id) "
                "DO UPDATE SET rules_json = excluded.rules_json",
                (competition_id, encoded),
            )
            connection.commit()
        self.registrations._notify_change()

    def linked_session(self, round_id: str) -> str | None:
        with closing(self.registrations._connect()) as connection:
            row = connection.execute(
                "SELECT session_id FROM round_score_links WHERE round_id = ?", (round_id,)
            ).fetchone()
        return row[0] if row else None

    def link(self, round_id: str, session_id: str) -> None:
        # Check and insert under the same write lock, including cross-league validation.
        try:
            with closing(self.registrations._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                round_ = connection.execute(
                    "SELECT * FROM competition_rounds WHERE id = ?", (round_id,)
                ).fetchone()
                session = connection.execute(
                    "SELECT * FROM league_sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if round_ is None or session is None:
                    raise RegistrationDataError("Round or score week was not found")
                if round_["competition_id"] != session["competition_id"]:
                    raise RegistrationDataError("Choose a score week from the same league")
                old = connection.execute(
                    "SELECT session_id FROM round_score_links WHERE round_id = ?", (round_id,)
                ).fetchone()
                if old:
                    if old[0] == session_id:
                        return
                    raise RegistrationDataError("This round already has a linked score week")
                if session["status"] != SessionStatus.DRAFT.value:
                    raise RegistrationDataError("Reopen the score week before linking it")
                if round_["status"] in (RoundStatus.CANCELLED.value, RoundStatus.POSTPONED.value):
                    raise RegistrationDataError("This round is not available for scoring")
                matches = connection.execute(
                    "SELECT left_team_id, right_team_id FROM competition_matches "
                    "WHERE round_id = ?",
                    (round_id,),
                ).fetchall()
                expected = {team for match in matches for team in match if team}
                actual = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT team_id FROM score_lines WHERE session_id = ?",
                        (session_id,),
                    )
                }
                if not matches or not actual or not actual <= expected:
                    raise RegistrationDataError("Score-sheet teams do not match this round")
                rule_row = connection.execute(
                    "SELECT rules_json FROM standing_rules WHERE competition_id = ?",
                    (round_["competition_id"],),
                ).fetchone()
                rules_json = rule_row[0] if rule_row else StandingRules().encode()
                connection.execute(
                    "INSERT INTO round_score_links VALUES (?, ?, ?, ?)",
                    (round_id, session_id, rules_json, datetime.now(UTC).isoformat()),
                )
                connection.execute(
                    "INSERT INTO score_change_log "
                    "(id, session_id, old_status, new_status, reason, changed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid4().hex, session_id, "Unlinked", f"Linked round {round_id}",
                     f"Round {round_['round_number']}; rules: {rules_json}",
                     datetime.now(UTC).isoformat()),
                )
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise RegistrationDataError(
                "This score week is already linked to another round"
            ) from error
        self.registrations._notify_change()

    def unlink(self, round_id: str, reason: str) -> None:
        if not reason.strip():
            raise RegistrationDataError("Enter a reason to unlink this round")
        with closing(self.registrations._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT l.session_id, s.status FROM round_score_links l "
                "JOIN league_sessions s ON s.id = l.session_id WHERE round_id = ?",
                (round_id,),
            ).fetchone()
            if row is None:
                return
            if row["status"] != SessionStatus.DRAFT.value:
                raise RegistrationDataError("Reopen the score week before unlinking it")
            connection.execute(
                "INSERT INTO score_change_log "
                "(id, session_id, old_status, new_status, reason, changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid4().hex,
                    row["session_id"],
                    f"Linked round {round_id}",
                    "Unlinked",
                    reason.strip(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.execute("DELETE FROM round_score_links WHERE round_id = ?", (round_id,))
            connection.commit()
        self.registrations._notify_change()

    def round_results(self, round_id: str) -> list[MatchResult]:
        return self._round_results(round_id, {})

    def _round_results(
        self,
        round_id: str,
        standings: dict[str, TeamStanding],
    ) -> list[MatchResult]:
        matches = self.schedules.list_matches(round_id)
        with closing(self.registrations._connect()) as connection:
            link = connection.execute(
                "SELECT * FROM round_score_links WHERE round_id = ?", (round_id,)
            ).fetchone()
            round_status = connection.execute(
                "SELECT status FROM competition_rounds WHERE id = ?", (round_id,)
            ).fetchone()[0]
        session = self.scores.get_session(link["session_id"]) if link else None
        rules = StandingRules(**json.loads(link["rules_json"])) if link else StandingRules()
        sheet = self.scores.score_sheet(session.id) if session else []
        totals = {t.team_id: t for t in self.scores.team_totals(session.id)} if session else {}
        results = []
        for match in matches:
            for team_id, name in (
                (match.left_team_id, match.left_team_name),
                (match.right_team_id, match.right_team_name),
            ):
                if team_id:
                    standings.setdefault(team_id, TeamStanding(team_id, name))
            state = "Final"
            if match.is_bye:
                state = "BYE — no points"
            elif round_status in (RoundStatus.CANCELLED.value, RoundStatus.POSTPONED.value):
                state = round_status
            elif match.status in (
                MatchStatus.CANCELLED,
                MatchStatus.POSTPONED,
                MatchStatus.FORFEIT,
            ):
                state = f"{match.status.value} — not counted"
            elif session is None:
                state = "Not linked"
            elif session.status is not SessionStatus.FINAL:
                state = "Draft — not counted"
            else:
                for team_id in (match.left_team_id, match.right_team_id):
                    rows = [view for view in sheet if view.line.team_id == team_id]
                    if not rows or any(
                        len(view.games) != session.games_per_player
                        or any(g.status is GameStatus.NOT_ENTERED for g in view.games)
                        for view in rows
                    ):
                        state = "Incomplete lineup — not counted"
            if state != "Final":
                results.append(MatchResult(match.id, match.matchup, state))
                continue
            left, right = totals[match.left_team_id], totals[match.right_team_id]
            left_games = left.scratch if rules.comparison == "Scratch" else left.counted
            right_games = right.scratch if rules.comparison == "Scratch" else right.counted
            lp, rp = Decimal(0), Decimal(0)
            ls, rs = standings[left.team_id], standings[right.team_id]
            for a, b in zip(left_games, right_games, strict=True):
                ap, bp = _points(a, b, rules.game_points, rules.ties)
                lp += ap
                rp += bp
                ls.game_wins += a > b
                rs.game_wins += b > a
                ls.game_losses += a < b
                rs.game_losses += b < a
                ls.game_ties += a == b
                rs.game_ties += a == b
            a, b = sum(left_games), sum(right_games)
            ap, bp = _points(a, b, rules.series_points, rules.ties)
            lp += ap
            rp += bp
            for entry, own, opponent, total, points in (
                (ls, a, b, left, lp),
                (rs, b, a, right, rp),
            ):
                entry.played += 1
                entry.wins += own > opponent
                entry.losses += own < opponent
                entry.ties += own == opponent
                entry.points += points
                entry.scratch_pins += total.scratch_total
                entry.handicap_pins += total.counted_total
            results.append(MatchResult(match.id, match.matchup, state, lp, rp, a, b))
        return results

    def standings(self, competition_id: str) -> list[TeamStanding]:
        rules = self.rules(competition_id)
        entries = {
            t.id: TeamStanding(t.id, t.name)
            for t in self.registrations.list_teams(competition_id, include_archived=True)
        }
        for round_ in self.schedules.list_rounds(competition_id):
            self._round_results(round_.id, entries)

        def key(entry: TeamStanding) -> tuple:
            primary = {
                "Series wins": entry.wins,
                "Game wins": entry.game_wins,
                "Points": entry.points,
            }[rules.ranking]
            secondary = {
                "None": 0,
                "Scratch pins": entry.scratch_pins,
                "Handicap pins": entry.handicap_pins,
            }[rules.tiebreaker]
            return primary, secondary

        ordered = sorted(entries.values(), key=lambda e: e.team_name.casefold())
        ordered.sort(key=key, reverse=True)
        previous = None
        rank = 0
        for index, entry in enumerate(ordered, start=1):
            if key(entry) != previous:
                rank = index
            entry.rank = rank
            previous = key(entry)
        return ordered


def _points(a: int, b: int, amount: str, ties: str) -> tuple[Decimal, Decimal]:
    points = Decimal(amount)
    if a == b:
        half = points / 2 if ties == "Split points" else Decimal(0)
        return half, half
    return (points, Decimal(0)) if a > b else (Decimal(0), points)
