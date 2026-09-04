# Persistent bowler database

Average Assistant 0.4 opens directly to the permanent bowler directory. The app
does not contain league registration, scheduling, scoring, or standings features.
The preserved league-manager code lives in `TheIlluminate92/usbc-league-manager`.

## Storage and migrations

The default database is `%LOCALAPPDATA%\Average Assistant\bowlers.sqlite3`.
`database.py` owns SQLite access. Each operation opens and closes its own
connection, enables foreign keys, and uses transactions; background workers never
share SQLite connections. WAL allows the interface to read completed results
while refresh workers commit. The Back up command uses SQLite's online backup API.

`PRAGMA user_version` tracks ordered transactional migrations:

1. Bowler identity, normalized names/aliases, and UI settings.
2. Current composite records, append-only change history, sanitized/versioned snapshots.
3. Normalized league activity and its retained revisions.

A newer schema is rejected without replacing the database. Failed migrations
roll back. A backup is a complete standalone database and can be restored to the
default path while the app is closed. Do not copy only the live database file
while the app is running; use Back up so WAL contents are included.

## Identity and importing

The USBC prefix-suffix ID is the durable identity. BOWL.com's internal member ID,
names, middle initial, gender, active status, association/state, dates, product,
and all returned boolean flags are normalized. Extra response fields remain in
sanitized JSON. Known IDs reuse their canonical record even if the imported name
changes. Distinct IDs can have identical names.

Repeated unresolved names reuse the unresolved input record. A name-only import
that may refer to a saved member asks the operator to choose the existing person
or create someone different. Name matching alone never silently merges confirmed
people. Imports validate the complete input before adding rows. Imported rows do
not automatically trigger a full database refresh.

Existing 0.3 CSV/XLSX/JSON rosters can be imported to seed the database. Those files
are identity inputs; their single flattened average is not treated as verified
BOWL.com history. Refresh fetches the authoritative records.

## Refresh

`services/refresh.py` coordinates four workers by default (configurable through
its service API from one to eight). It schedules only one task per available
worker. Each task owns an HTTP client and its snapshot collection. Each request
has a 20-second timeout. Results are saved atomically per bowler, then a progress
event is delivered to the UI's main-thread queue.

Known bowlers use the saved USBC ID, bypassing name search. Unresolved names with
multiple distinct IDs are stored for explicit resolution. Multiple membership
rows for the same ID are retained in snapshots; the newest active membership
supplies the primary displayed fields.

The collector follows all reported pages for `members/`, `members/id`,
`compositeaverages`, and `leagueactivities`. Missing/malformed successful payloads
and incomplete pagination are errors, not empty successful refreshes. Cancellation
stops further scheduling and page requests, drains bounded in-flight requests,
and preserves completed commits. Authentication expiry and HTTP 429 stop the batch.
Other per-bowler failures leave prior data intact and allow other bowlers to finish.
An unavailable league-activity response saves the successful member/composite data
as a partial refresh and keeps previously stored league data.

Composite records use `(bowler, year, sport, challenge, hand)` as the current-record
key. Changed games, averages, or raw fields append a revision. Absent old years are
not deleted. Every returned same-key variant is captured in revision history;
the last returned variant is the current value. Identical refreshes update the
observation timestamp without duplicating revisions. League records retain their
IDs, season, center, association, year, average/games, adjusted average, pattern,
hand, and sport/challenge/string-pin/bumper/roll-and-grow flags.

`relatedaverages` was observed in an earlier browser capture, but no request
contract or response fixture is available in the source branches. It is not
requested speculatively. A sanitized request/response sample is needed to add it.

## Export

`services/database_exports.py` only reads stored data; it never calls BOWL.com.
Export scopes are Selected, Visible, and All. The preview supports Composite,
League, or Adjusted league sources; Latest, Highest, Specific year, or explicit
manual selection per bowler; Standard/Sport/Challenge/Any type; hand and minimum
games filters. Minimum games/type/hand filters apply to automatic rules. Manual
selection is an explicit record override. A source change clears manual choices.

Years are BOWL.com's raw season-ending year (for example, 2025 means 2024–2025).
Ties are resolved deterministically by year, average, games, hand, and record ID;
Highest starts with average. Missing records default to blocking export until the
operator chooses blank averages or skipping unmatched bowlers. Missing values
are never silently converted to zero. Adjusted league records with no positive
adjusted average are ineligible.

BTM26+ CSV columns, in order:

`First Name,Middle Initial,Last Name,Gender,Book Average,Book Games,USBC ID Number`

In BTM's CSV import wizard, skip one header line, map these columns, and map
Middle Initial to Middle Name. The confirmed BTM field list has no team assignment
field; assign teams inside BTM after importing. Generic CSV/XLSX add the selected
year/type/hand/source and member/status context. JSON preserves the preview data.
All exports use an atomic temporary-file replacement, and CSV/XLSX neutralize
formula-like strings. Export never changes stored averages or snapshots.

## Interface and sign-in

`database_app.py` owns the directory and background-job state; `ui.py` contains
dialogs. Tk calls run on the main thread. Double-click opens member information,
stored averages, revisions, league activity, sanitized API data, and identity
resolution when needed. Search/filter/sort, window geometry, and export folder
persist. Refresh Selected/Visible/All and Cancel stay on the main toolbar.

The private WebView helper and quiet close/cancel handling are back-ported from
`feature/manual-registration`. The helper emits one result, stops its watcher on
close, and keeps browser storage private. The application ignores late sign-in
results after cancellation/sign-out and never persists bearer tokens.

## Verification

Run `python -m ruff check .` and `python -m pytest`. The Windows CI suite includes
real Tk directory/dialog, export-preview, background-refresh, and sign-in-cancel
integration checks. Network behavior uses synthetic fixtures, including failure,
pagination, cancellation, rate limit, duplicate, migration, history, and export tests.
Live BOWL.com sign-in and a real BTM import remain operator acceptance checks.
