"""Bounded, cancellable harvesting with one API client per bowler and atomic saves."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from threading import Event

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.models import Member
from usbc_average_lookup.services.bowl_api import (
    ApiCancelledError,
    AuthenticationExpiredError,
    BowlApi,
    BowlApiError,
    RateLimitedError,
)
from usbc_average_lookup.services.sanitize import sanitize


@dataclass(frozen=True)
class RefreshEvent:
    bowler_id: int
    status: str
    note: str = ""
    completed: int = 0
    total: int = 0


def refresh_one(
    database: BowlerDatabase, api: BowlApi, bowler_id: int, cancel: Event
) -> RefreshEvent:
    row = database.get(bowler_id)
    try:
        if cancel.is_set():
            return RefreshEvent(bowler_id, "Cancelled")
        # Saved membership IDs always bypass name searching.
        matches = list(
            api.search_members(
                name="" if row["membership_id"] else row["display_name"],
                membership_id=row["membership_id"] or "",
            )
        )
        if cancel.is_set():
            return RefreshEvent(bowler_id, "Cancelled")
        if row["membership_id"]:
            matches = [m for m in matches if f"{m.prefix}-{m.suffix}" == row["membership_id"]]
        identities = {f"{member.prefix}-{member.suffix}" for member in matches}
        if not matches:
            database.save_status(bowler_id, "Not found", "Check the name or USBC ID")
            return RefreshEvent(bowler_id, "Not found")
        if len(identities) > 1:
            database.save_status(
                bowler_id, "Choose member", "Open details to select a match", matches
            )
            return RefreshEvent(bowler_id, "Choose member")
        member = max(matches, key=lambda m: (m.active, m.membership_thru, m.membership_from))
        averages = list(api.get_composite_averages(member.prefix, member.suffix))
        league_averages = []
        warning = ""
        if not cancel.is_set() and hasattr(api, "get_league_averages"):
            try:
                league_averages = list(api.get_league_averages(member.prefix, member.suffix))
            except RateLimitedError:
                raise
            except BowlApiError:
                warning = "League activity could not be refreshed; previous league data is retained"
        if cancel.is_set():
            return RefreshEvent(bowler_id, "Cancelled")
        snapshots = dict(getattr(api, "snapshots", {}))
        # Keep only the chosen identity's member rows, never an unrelated name-search roster.
        snapshots.pop("members/", None)
        snapshots.setdefault("member", [m.raw or asdict(m) for m in matches])
        snapshots.setdefault("compositeaverages", [a.raw or asdict(a) for a in averages])
        note = "" if averages else "No composite averages returned; stored history is retained"
        note = "; ".join(part for part in (note, warning) if part)
        canonical_id = database.save_refresh(
            bowler_id, member, averages, snapshots, note, league_averages=league_averages
        )
        if warning:
            database.save_status(canonical_id, "Partial refresh", note)
        return RefreshEvent(canonical_id, "Partial refresh" if warning else "Refreshed", note)
    except ApiCancelledError:
        return RefreshEvent(bowler_id, "Cancelled")
    except RateLimitedError as error:
        cancel.set()
        database.save_status(bowler_id, "Rate limited", str(error))
        return RefreshEvent(bowler_id, "Rate limited", str(error))
    except AuthenticationExpiredError:
        cancel.set()
        database.save_status(bowler_id, "Sign in again", "BOWL.com session expired")
        return RefreshEvent(bowler_id, "Sign in again", "BOWL.com session expired")
    except (BowlApiError, ValueError, OSError) as error:
        note = str(sanitize(str(error))) or "Refresh failed; saved data is unchanged"
        database.save_status(bowler_id, "Refresh failed", note)
        return RefreshEvent(bowler_id, "Refresh failed", note)


def refresh_bowlers(
    database: BowlerDatabase,
    api_factory: Callable[[], BowlApi],
    bowler_ids: Iterable[int],
    *,
    workers: int = 4,
    cancel: Event | None = None,
    progress: Callable[[RefreshEvent], None] | None = None,
) -> list[RefreshEvent]:
    """At most 1–8 tasks in flight. Callbacks run on the coordinator, not the GUI thread.

    Cancellation stops scheduling, drains the bounded in-flight requests, and preserves
    completed commits. Authentication expiry triggers the same stop behavior.
    """
    if not 1 <= workers <= 8:
        raise ValueError("Choose between 1 and 8 refresh workers")
    stop = cancel if cancel is not None else Event()
    ids = list(dict.fromkeys(bowler_ids))
    remaining = iter(ids)
    events: list[RefreshEvent] = []

    def run(bowler_id: int) -> RefreshEvent:
        return refresh_one(database, api_factory(), bowler_id, stop)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bowler") as pool:
        pending = {}

        def fill() -> None:
            while len(pending) < workers and not stop.is_set():
                bowler_id = next(remaining, None)
                if bowler_id is None:
                    return
                pending[pool.submit(run, bowler_id)] = bowler_id

        fill()
        while pending:
            done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                bowler_id = pending.pop(future)
                try:
                    result = future.result()
                except Exception:
                    # Do not expose unknown transport exceptions, which can contain headers.
                    result = RefreshEvent(
                        bowler_id,
                        "Refresh failed",
                        "Unexpected refresh error; saved data is unchanged",
                    )
                    database.save_status(bowler_id, result.status, result.note)
                event = RefreshEvent(
                    result.bowler_id, result.status, result.note, len(events) + 1, len(ids)
                )
                events.append(event)
                if progress:
                    progress(event)
            fill()
    return events


def stored_candidates(row: dict) -> list[Member]:
    import json

    return [Member(**value) for value in json.loads(row["candidates_json"])]
