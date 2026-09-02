# USBC Average Lookup

A small Windows desktop manager for registering bowlers by league season or
tournament, organizing season-specific teams, and turning bowler names into
verified averages using BOWL.com's JSON-backed member search and average data.

> [!IMPORTANT]
> This is an early, unofficial foundation. It is not affiliated with or endorsed
> by the United States Bowling Congress (USBC) or BOWL.com. Endpoint details,
> authentication requirements, and permission to automate access must be
> confirmed before real lookups are enabled.

## Intended workflow

### Registration Desk

The workspace is divided into four focused tabs:

- **Registration** for fast individual and whole-team entry
- **Players** for the permanent directory and year-by-year player pools
- **Teams** for league/tournament-filtered regular and substitute rosters
- **Leagues & Tournaments** for creating, editing, archiving, and restoring
  competition workspaces

1. Create a league season or tournament workspace.
2. Add its teams as they are known; an unassigned option remains available.
3. Enter one bowler at a time or paste a complete team roster.
4. Keep registering while signed-in BOWL.com checks run through a two-worker
   queue in the background.
5. Review only ambiguous or unsuccessful matches. Registrations save
   automatically after each change.

The bowler is a reusable identity. A season player pool is a separate reusable
list that can be copied forward, then adjusted without changing the prior year.
A league or tournament can link to one pool, while registrations and team
assignments still belong only to that competition. Regulars and substitutes can
be assigned to a team; an unassigned substitute remains in the league-wide
substitute pool. Removing someone from a team does not remove their league
registration or permanent player record. Duplicate registrations within one
competition are rejected.

Registration data is stored locally in a versioned SQLite database at
`%LOCALAPPDATA%\Bowling Manager\bowling-manager.db`. Each save is a database
transaction, with foreign-key and uniqueness checks protecting linked records.
On first launch after upgrading, the app can import the former
`registration-data.json` file. The original remains unchanged and an additional
`registration-data.pre-sqlite-backup.json` copy is created before the new
database becomes active. An unreadable or unsupported database is left
unchanged rather than silently replaced.

### Average lookup

1. Sign in only when a BOWL.com lookup is needed.
2. Choose a roster file, or use **Single lookup** for one bowler by name or
   membership ID.
3. Click **Look Up Averages**.
4. Pick the right person only when the app finds more than one match.
5. Click **Save Results** to create the result file.

The app never asks for or stores a BOWL.com password. Authentication opens the
real BOWL.com page in a private sign-in window owned by Average Assistant. It
does not open tabs in Edge, Chrome, or Brave. **Sign out** and closing the app
discard the in-memory session; the private window does not retain cookies or
browser storage.
Version 0.3.0 also removes the app-owned browser profiles left by older builds;
it does not touch the user's normal browser data.

## Result states

Every input name receives exactly one visible result:

- `Found`
- `Not found`
- `Multiple matches`
- `No average`
- `Inactive member`
- `Login expired`
- `API error`

Only `Found` rows belong in the clean `Name,Average` export. All other rows are
retained in the UI and issue export with an explanatory note.

## Input formats

The current parser accepts `.csv`, `.tsv`, `.txt`, `.json`, and `.xlsx`
files. Delimited text may use commas, tabs, pipes, or semicolons, and a header is
optional. These formats are a flexible starting point rather than a frozen
interchange contract; support can evolve once representative league files are
available:

```csv
Name,Membership ID
Alex Bowler,1234-567890
Jamie Bowler,
```

It also accepts one entry per line:

```text
Alex Bowler (1234-567890)
Jamie Bowler
```

## JSON output

Every input row remains visible in the output, including failures:

```json
{
  "schemaVersion": 2,
  "generatedAt": "2026-08-30T12:00:00+00:00",
  "summary": {
    "processed": 2,
    "found": 1,
    "not_found": 1
  },
  "bowlers": [
    {
      "name": "Alex Bowler",
      "membershipId": "1234-567890",
      "average": 187,
      "status": "Found",
      "notes": null
    }
  ]
}
```

## What is included

- A runnable Tkinter Windows GUI with Registration Desk and Average Lookup tabs
- A local, schema-versioned SQLite database with transactional saves and
  automatic import of the former JSON store
- Persistent league-season and tournament workspaces
- Copy-forward season player pools kept separate from the permanent directory
- Season-specific teams with regular rosters, team substitutes, a league-wide
  substitute pool, reassignment, and withdrawal/restore controls
- Player, team, and league/tournament management tabs, with teams explicitly
  filtered by competition
- Background registration checks capped at two concurrent BOWL.com requests
- Registration counters for total, ready, and needs-attention entries
- Domain models for members, composite averages, and lookup outcomes
- Verified selection logic for the newest standard composite record
- Browser-based BOWL.com sign-in through the genuine site; passwords are never
  exposed to the application
- JSON export containing every input row, status, average, and notes
- Unit tests and a GitHub Actions workflow
- Requirements, architecture, and API discovery notes under [`docs/`](docs/)

## Run locally

Python 3.11 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m usbc_average_lookup
```

The sign-in flow opens one private WebView2 window containing the genuine
BOWL.com page and waits for the site to establish an authenticated API session.
The temporary session token is held only in memory and is never written to
application logs or configuration. The entire private WebView process is ended
after sign-in, on sign-out, and when Average Assistant closes.

## Run tests

```powershell
python -m pytest
```

## Project layout

```text
src/usbc_average_lookup/
  app.py                 Windows GUI shell
  registration_ui.py     Manual-first registration workflow
  models.py              Shared member, average, and result types
  services/
    auth.py              Private WebView2 sign-in boundary
    average_selector.py  Composite-average selection rule
    bowl_api.py          Member-search and average API boundary
    exports.py           Results and issues CSV output
    registration.py      Versioned local registration store and domain rules
tests/                    Unit tests
docs/                     Requirements, architecture, and discovery notes
```

## Next milestones

1. Test the Registration Desk with representative handwritten league and
   tournament rosters, then refine the keyboard workflow and terminology.
2. Test season-pool copy-forward and regular/substitute roster changes with a
   real four-league weekly schedule.
3. Confirm BOWL.com/USBC terms and acceptable request volume before broader use.
4. Test signed-out, expired-session, rate-limit, and unexpected-response behavior
   against the real endpoints.
5. Complete the final release checklist on the packaged Windows build, especially
   privacy, process cleanup, memory, and large-roster checks.
6. Package a signed or clearly identified portable Windows executable.
7. Define the acceptance and release criteria for promoting the experimental
   review workflow to a normal release.

QR self-registration and bracket/side-pot money handling are deliberately
deferred. They are not part of the current registration workflow.

See [`docs/requirements.md`](docs/requirements.md) for acceptance criteria and
[`docs/api-notes.md`](docs/api-notes.md) for what is known versus still unknown.
Before a build is considered ready, run the permanent
[`final release checklist`](docs/release-checklist.md), including memory,
process-cleanup, workload, and privacy checks.
