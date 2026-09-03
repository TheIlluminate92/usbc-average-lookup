# Bowling Manager

Bowling Manager is a local Windows desktop application for running small
bowling leagues and tournaments. It combines reusable player records,
season-specific teams and rosters, BOWL.com average lookup, customizable league
average/handicap settings, and permanent weekly score sheets in one interface.

The repository and executable still use the historical name
`usbc-average-lookup` in several technical places.

> [!IMPORTANT]
> This is an unofficial pre-alpha project. It is not affiliated with or
> endorsed by USBC or BOWL.com. The BOWL.com endpoints used by the lookup are
> not a supported public data-mining API, and acceptable use and request volume
> still need confirmation. Use it only for records you are authorized to
> manage.

## Download

The current portable Windows test build is
[v0.6.0-alpha.2](https://github.com/TheIlluminate92/usbc-average-lookup/releases/tag/v0.6.0-alpha.2).
Download `USBC-Average-Lookup-Windows.zip`, extract the entire folder, and run
`USBC-Average-Lookup.exe`.

The executable is portable, but its working database is not stored beside the
executable. Application data lives at:

```text
%LOCALAPPDATA%\Bowling Manager\bowling-manager.db
```

Back up that database while the application is closed. Copying only the
extracted program folder does not copy league data.

## Current application

The compact browser-style strip opens on Registration and has three top-level
workspaces. Use **+ New window**, right-click a top-level tab, or use **Open
view in new window** inside League Manager to work side by side. A detached
view can return its current section and league selection to the main window.

- **Registration** supports fast single-player entry, whole-team entry, and
  one-step registration into multiple leagues with a separate team assignment
  for each.
- **League Manager**
  - **League home** summarizes the selected competition and its work queue.
  - **Teams & roster** manages regulars, team substitutes, and the league-wide
    substitute pool in one master-detail view.
  - **Scores & history** stores permanent weekly score sheets, individual
    games, calculated team totals, and correction history.
  - **Rules & setup** keeps league details, average/handicap rules, scoring
    defaults, and the linked player pool together.
  - **Player directory** maintains one permanent identity per person and
    optional year/season player pools.
  - **Leagues & seasons** creates and archives league-season or tournament
    workspaces, links player pools, manages teams and players, and opens score
    history.
- **Average lookup** imports a roster or accepts one player, checks BOWL.com,
  resolves ambiguous matches, exports results, and can add the result list to
  the permanent player directory.

Double-click a league, team, or player in its management table to open the
relationship browser. Editing remains on the clearly labeled edit buttons.

## Typical workflow

1. Create a league season such as `Monday Misfits — 2026-27`.
2. Add or copy teams and build the season roster from the permanent player
   directory.
3. Register new bowlers manually. A bowler can join several leagues in one
   operation and use a different team in each.
4. Sign in to BOWL.com only when average verification is needed. Manual league
   management and score entry work while signed out.
5. Configure the league's average transformation, handicap, blind, vacancy,
   and games-per-night settings.
6. Create a weekly score sheet. Active regular rosters are snapshotted into
   that week.
7. Add substitutes, vacancies, or a previously removed player; enter games;
   review team totals; and finalize the week.
8. Reopen a final week only with a reason. Corrections remain in the permanent
   change log.

See the [user guide](docs/user-guide.md) for detailed operating instructions.

## What is implemented

- Local schema-versioned SQLite storage with transactional writes, foreign-key
  checks, uniqueness checks, legacy JSON import, and pre-upgrade backups.
- Permanent players shared across league seasons and tournaments.
- Independently editable year/season player pools.
- League-season and tournament workspaces with archive/restore.
- Competition-specific teams, regular rosters, team substitutes, and a
  league-wide substitute pool.
- Copying a prior team and optionally its active roster into a new season.
- Multi-league registration with existing or newly created teams; the entire
  operation rolls back if any target fails.
- Two-worker background average checks from Registration so an ambiguous name
  does not block entry of the next bowler.
- Private BOWL.com WebView2 sign-in and in-memory bearer-token handling.
- Name or membership-ID lookup, explicit ambiguous-member selection, and the
  newest eligible Standard Composite Average.
- CSV, TSV, text, JSON, and `.xlsx` input.
- JSON, CSV, TSV, text, and `.xlsx` result export with full, ready, inactive,
  and needs-attention subsets.
- Importing average-lookup results into the permanent player directory.
- League-specific composite multiplier, pin adjustment, minimum games,
  rounding, handicap base/percentage, blind penalty, vacancy score, and
  games-per-session settings.
- Permanent weekly individual scores with Bowled, Blind, Absent, Vacancy, and
  Not entered states.
- Derived team scratch and handicap totals, draft/final states, team-filtered
  history, and reasoned correction logs.
- Relationship navigation in both directions between leagues, teams, and
  players.
- One shared league/tournament context across Registration, Teams, Rules, and
  Scores, with automatic refresh after a database change.
- Browser-style workspace chrome and synchronized Registration or League
  Manager windows. Detached management windows may stay on different leagues;
  score-entry dialogs prevent simultaneous editing of the same weekly sheet.

## Important current limits

- Average lookup uses the verified Standard Composite source. The rule engine
  can model league-activity sources, but raw league activities are not yet
  retained on registrations and cannot yet be selected in the league settings
  screen.
- Member name search follows the BOWL.com frontend's first page of ten results.
  For very common names, a membership ID is the reliable search path.
- Weekly score sheets do not yet define team matchups, lanes, points,
  standings, schedules, leaderboards, or recap-sheet exports.
- Score rows currently use a fixed team/name order. Clickable ascending and
  descending team sorting is still planned.
- There is no bracket, side-pot, payout, or other money-handling module.
- There is no shared server, user login, cloud synchronization, or concurrent
  multi-computer editing. The SQLite file is local to one Windows profile.
- Registration and League Manager can open in additional windows. Average
  lookup currently remains in the main window.
- Input and output formats remain intentionally flexible until representative
  league and tournament files are available.
- The Windows test build is unsigned and is not an installer.

## Input files

The lookup parser accepts `.csv`, `.tsv`, `.txt`, `.json`, and `.xlsx`.
Delimited files may use commas, tabs, pipes, or semicolons. It recognizes common
name and membership-ID headings, combined names, separate first/last columns,
and simple lines such as:

```text
Alex Bowler (1234-567890)
Jamie Bowler
```

Example CSV:

```csv
Name,Membership ID
Alex Bowler,1234-567890
Jamie Bowler,
```

When an Excel workbook has more than one non-empty sheet, the application asks
which sheet to use. Legacy `.xls` is not supported.

## Lookup result states

Every imported row remains visible and ends in one of these states:

- `Found`
- `Not found`
- `Multiple matches`
- `No average`
- `Inactive member`
- `Login expired`
- `API error`

The **Fixes needed** tab contains unresolved rows. The operator can select a
candidate, correct a name or member ID, retry one row, and move to the next
issue without rerunning completed rows.

## Data, privacy, and backups

The database contains names, optional USBC membership IDs, league/team
associations, averages, and scores in ordinary local SQLite tables. It is not
encrypted by the application. Windows account and disk protections are the
current access boundary.

BOWL.com passwords never enter the application. Sign-in occurs on the genuine
BOWL.com page in a private helper window. The resulting bearer token is kept in
memory and discarded on sign-out or application close. See
[SECURITY.md](SECURITY.md) for the complete security model.

Schema upgrades create a one-time backup beside the database, for example:

```text
bowling-manager.schema-v1-backup.db
bowling-manager.schema-v2-backup.db
```

Legacy `registration-data.json` import leaves the original file unchanged and
creates `registration-data.pre-sqlite-backup.json`.

## Development

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m usbc_average_lookup
```

Run the automated checks:

```powershell
python -m ruff check .
python -m pytest
```

Build dependencies are optional:

```powershell
python -m pip install -e ".[build]"
```

Tagged releases trigger the Windows packaging workflow. It creates the private
sign-in helper, packages the application with PyInstaller, verifies that the
helper starts, uploads a short-lived Actions artifact, and publishes a
pre-release ZIP.

## Project layout

```text
src/usbc_average_lookup/
  app.py                 Main window and average-lookup workflow
  registration_ui.py     League, player, team, and registration screens
  relationships_ui.py    League/team/player relationship browser
  scoring_ui.py          Weekly scoring and history screens
  signin_helper.py       Private WebView2 sign-in process
  models.py              Lookup data and result states
  services/
    auth.py              Sign-in process boundary and in-memory session
    average_rules.py     Configurable average-rule engine
    average_selector.py  Standard composite selection
    bowl_api.py          BOWL.com JSON client and response validation
    exports.py           JSON, delimited, and Excel output
    input_parser.py      Flexible roster input
    registration.py      SQLite schema and registration domain
    scoring.py           Weekly scores, totals, and audit history
tests/                    Automated behavior and regression tests
docs/                     User, architecture, requirements, API, and release docs
```

## Documentation

- [User guide](docs/user-guide.md)
- [Current requirements and scope](docs/requirements.md)
- [Architecture and data model](docs/architecture.md)
- [Scoring and standings plan](docs/scoring-plan.md)
- [BOWL.com API observations](docs/api-notes.md)
- [Release checklist](docs/release-checklist.md)
- [Security policy](SECURITY.md)
- [Change log](CHANGELOG.md)

## Next milestones

1. Exercise registration, roster changes, and scoring with the real four-league
   weekly schedule and occasional tournaments.
2. Replace multi-selection gestures with clearer checkbox-style controls and
   make score entry more keyboard-friendly.
3. Add weekly matchups and configurable points, then derive standings only from
   finalized score sheets.
4. Retain raw league activities so a league can select prior-league or adjusted
   averages instead of only Standard Composite.
5. Define recap-sheet imports/exports after representative files are available.
6. Complete packaged-build resource, privacy, and 200-bowler workload checks.

QR self-registration remains a parked future idea. Brackets and other money
handling remain deliberately out of scope.
