# Architecture and data model

## Overview

Bowling Manager is a single-user Windows desktop application. Tkinter owns the
main UI, a short-lived WebView2 helper owns BOWL.com sign-in, an HTTP client
performs authenticated JSON requests, and SQLite stores local league data and
score history.

```text
Tkinter application
  |
  +-- compact browser-style workspace shell
  |     +-- Registration / League Manager / Average lookup
  |     +-- additional synchronized Registration or management windows
  |
  +-- League Manager
  |     +-- shared LeagueWorkspaceContext
  |     +-- league home and rules/setup
  |     +-- leagues / seasons / tournaments
  |     +-- permanent players and season pools
  |     +-- competition teams and rosters
  |     +-- competition rounds, matchups, BYEs, and lane pairs
  |     +-- weekly score sheets and history
  |
  +-- Registration
  |     +-- single, whole-team, and multi-league entry
  |     +-- two-worker background verification queue
  |
  +-- Average lookup
  |     +-- flexible file parser
  |     +-- member matching and issue review
  |     +-- result subsets and exports
  |
  +-- private sign-in helper process
  |     +-- genuine BOWL.com page in private WebView2
  |     +-- temporary bearer token through stdout pipe
  |
  +-- HttpBowlApi
  |     +-- member search
  |     +-- composite averages
  |     +-- league activities (client support only)
  |
  +-- RegistrationStore / ScheduleStore / ScoringStore / StandingsStore
        +-- SQLite schema version 6
```

## UI composition

`AverageLookupApp` is the application shell. It owns authentication state, the
compact workspace strip, and the three top-level workspaces:

- Registration
- League Manager
- Average lookup

`RegistrationDesk` controls the separate Registration workspace and the seven
League Manager sections. `LeagueWorkspaceContext` propagates one selected
competition across Registration, Teams, Schedule, Scores, Rules, and Home.

Additional windows construct another desk against the same store but receive
an independent workspace context. `RegistrationStore` change listeners schedule
refreshes for every open desk after a committed write. `ScoreSheetEditLocks`
prevents two score-entry dialogs from editing one weekly session concurrently.
Average lookup remains owned by the main application shell and is not currently
detachable.

`ScheduleDesk` and `ScoringDesk` are mounted inside League Manager.
`RelationshipBrowser` opens as
a separate navigation window and holds its own Back/Forward history.

UI classes call domain stores rather than SQL. The stores validate rules, save
data, and return view models. Message boxes translate expected validation
errors into operator-facing language.

## Registration data model

The current normalized management records are:

| Record | Purpose |
| --- | --- |
| `BowlerProfile` | Reusable person identity and optional USBC member ID |
| `PlayerPool` | Independently editable year/season list |
| `PlayerPoolEntry` | Many-to-many link from pool to player |
| `Competition` | One league season or one tournament plus its scoring rules |
| `Team` | Team belonging to exactly one competition |
| `Registration` | Player's participation, team, role, lookup state, average, and withdrawal state in one competition |

Key invariants:

- A player identity can have many registrations but only one registration in a
  specific competition.
- A team belongs to one competition and team names are unique inside that
  competition.
- A registration's team, when present, must belong to the same competition.
- Removing a team assignment does not delete the registration or player.
- Withdrawal is separate from team assignment.
- A linked player pool is reusable and does not own teams or registrations.

`RegistrationTarget` is an in-memory command object for multi-league
registration. Each target names a competition and either an existing team, a
pending new team name, or no team. `register_bowler_many` snapshots all affected
collections, applies every target, writes once, and restores the snapshot if
any target fails.

## Scheduling data model

`Competition` selects Round robin, Single elimination, or Custom/manual format.
The first 0.7 implementation generates Round robin schedules into:

| Record | Purpose |
| --- | --- |
| `CompetitionRound` | One numbered week/round, stage, date, and state |
| `CompetitionMatch` | Two teams or an explicit BYE plus a lane pair and state |

The circle rotation creates `n - 1` rounds for an even team count. An odd count
receives an internal BYE position and `n` rounds. Match and lane assignment are
stored separately so future points use explicit opponents instead of inferring
them from lane order.

Team IDs and displayed names are snapshots rather than foreign keys to the
mutable live roster. This matches weekly score history: later team renames do
not rewrite an existing schedule. A match retains a foreign key only to its
own round so focused schedule deletion can remain atomic.

## Scoring data model

Historical scoring uses deliberate snapshots:

| Record | Purpose |
| --- | --- |
| `LeagueSession` | One league/week score sheet, date, label, frozen game count, and Draft/Final state |
| `ScoreLine` | Frozen player/team/role/average/handicap/lineup identity for one week |
| `GameScore` | One game state, scratch score, and counted pins |
| `ScoreChange` | Append-only before/after correction or session-state change |

Current registrations remain normalized. Score lines duplicate display names
and calculations so later player edits, team renames, roster moves, or rule
changes cannot rewrite a prior week.

Active regulars with teams are snapshotted when a session is created. A
registered player can be added to any team in the same league for that week
without changing the season roster. Vacancy rows have no player or registration
foreign key.

Team totals are projections over game records:

```text
team scratch game N = sum(player scratch game N or 0)
team counted game N = sum(player counted pins game N)
```

They are never separately persisted as editable totals.

## Average and handicap model

Lookup selection and league calculation are separate:

1. `average_selector.py` chooses the newest qualifying BOWL.com Standard
   Composite record.
2. The selected raw average, year, and games are saved on the registration.
3. The competition rule applies minimum games, multiplier, pin adjustment, and
   rounding.
4. Handicap is calculated from the resulting entering average.
5. The entering average and handicap are snapshotted on the score line.

The general `average_rules.py` engine can model Standard Composite, raw league
activity, and adjusted league activity candidates with source priority and
filters. The current registration store constructs only a Standard Composite
candidate because raw league activities are not yet persisted.

## SQLite storage

`RegistrationStore` owns the database at:

```text
%LOCALAPPDATA%\Bowling Manager\bowling-manager.db
```

Schema version 5 contains:

- `metadata`
- `player_pools`
- `bowlers`
- `competitions`
- `teams`
- `player_pool_entries`
- `registrations`
- `league_sessions`
- `score_lines`
- `game_scores`
- `score_change_log`
- `competition_rounds`
- `competition_matches`
- `standing_rules` (current rules for new links and table ranking)
- `round_score_links` (unique round/week link with immutable points-rule snapshot)

`StandingsStore` derives results from finalized linked score sheets; standings
are not independently writable totals. Draft/reopened weeks are excluded.
Link/unlink changes are recorded in `score_change_log`, and score writes notify
the shared store so open views refresh. Version-4 databases are automatically
backed up before the additive version-5 migration.

SQLite foreign keys are enabled on every connection. Tables use primary keys,
uniqueness constraints, and state `CHECK` constraints. The store validates
in-memory references before rewriting management tables.

Management saves run in one `BEGIN IMMEDIATE` transaction and rewrite only the
normalized management tables. Scoring methods use focused row-level
transactions against scoring tables. Normal management saves therefore do not
delete or regenerate weekly history.

### Schema upgrades

Before upgrading an existing SQLite database, `_backup_before_schema_upgrade`
uses SQLite's backup API to create one adjacent copy named for the old version,
such as `bowling-manager.schema-v2-backup.db`. Existing copies are retained and
not overwritten.

If the database version is newer than the application supports, opening fails
without changing the file.

### Legacy JSON migration

When no SQLite database exists but `registration-data.json` does, the store can
import JSON schema version 1 or 2. It:

1. loads and validates the legacy document;
2. preserves the source;
3. creates `registration-data.pre-sqlite-backup.json` if absent;
4. builds a temporary SQLite database;
5. runs integrity and foreign-key checks;
6. atomically moves the verified database into place.

## Authentication boundary

`WebViewAuthenticator` starts `Average-Assistant-SignIn.exe` in packaged builds
or the `signin_helper` module in development. The helper owns pywebview on its
main GUI thread and opens the genuine BOWL.com page with Edge Chromium and
`private_mode=True`.

The helper inspects its own page's local/session storage for a bearer token. It
prints one prefixed JSON response to the parent process. The main app parses the
response, keeps the token in an `AuthSession` field excluded from repr output,
and always terminates the helper.

No password is exposed to application code. The token is not written to SQLite,
files, logs, configuration, or exports. Closing, timing out, signing out, and
application shutdown terminate the helper. Versions 0.3 and later also remove
only known legacy app-owned browser-profile directories.

This is a pragmatic local-process boundary, not a hardened credential vault.
The local Windows account remains trusted.

## Lookup integration

`HttpBowlApi` sends authenticated `GET` requests with a 20-second timeout. It
uses separate member name and member-ID routes, then requests composite averages
for a chosen member. League-activity pagination is implemented in the client but
not yet part of normal registration storage.

Response parsing is defensive:

- top-level responses must be dictionaries;
- required `data.results` members must be lists;
- known records validate required value types;
- league pagination validates nonnegative integer `totalPages`;
- HTTP 401/403 maps to expired authentication;
- transport, decode, schema, and service errors map to safe lookup outcomes.

Name search currently follows the observed frontend request of Page 1 and Size
10. It does not page the entire member directory.

## Lookup coordination and concurrency

The Average lookup roster worker runs off the UI thread but calls
`look_up_all` sequentially. A monotonically increasing `lookup_generation`
prevents late work from replacing a newer roster or corrected result.

Registration has a fixed queue with two daemon worker threads. Each job keeps
the API object captured at queue time, updates the stored verification state,
and posts completion back to Tkinter with `after`. A set tracks outstanding
bulk checks for the group counter.

The application does not currently implement retry/backoff scheduling or
adaptive request concurrency.

## Import and export boundaries

`input_parser.py` normalizes CSV, TSV, delimited text, JSON, and `.xlsx` into
`InputBowler` records. Parsing is independent from network lookup.

`exports.py` projects `LookupResult` records into selected subsets and JSON,
Excel, CSV, TSV, or text. Spreadsheet-oriented output protects cells beginning
with formula prefixes. JSON schema version 2 includes the selected roster type,
status counts, and all selected bowler records.

League registration/scoring import and recap-sheet export are not yet defined;
the lookup file formats must not be mistaken for a final league interchange
contract.

## Packaging and CI

Windows CI runs Ruff and pytest on Python 3.11. Tagged builds:

1. install the build dependencies;
2. package the sign-in helper as a one-file console executable;
3. package the main app as a windowed one-directory executable;
4. verify that the packaged helper starts and returns a prefixed response;
5. upload the directory as a 14-day Actions artifact;
6. compress the directory and publish a GitHub pre-release ZIP.

The build is currently unsigned and has no installer or auto-update system.

## Design principles

- **Local first:** one operator and one Windows profile do not need a server.
- **Manual first:** local management remains available when BOWL.com is not.
- **Historical stability:** mutable current rosters and immutable-by-default
  score snapshots are different models.
- **No silent identity matching:** ambiguity is an operator decision.
- **Derived totals:** source player games are authoritative.
- **Reasoned corrections:** historical changes must be explainable.
- **Flexible edges:** import/export contracts remain adaptable until real files
  establish the required shapes.
