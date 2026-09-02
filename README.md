# USBC Average Lookup

A small Windows desktop utility for turning a list of bowler names into
`Name,Average` results using BOWL.com's JSON-backed member search and composite
average data.

> [!IMPORTANT]
> This is an early, unofficial foundation. It is not affiliated with or endorsed
> by the United States Bowling Congress (USBC) or BOWL.com. Endpoint details,
> authentication requirements, and permission to automate access must be
> confirmed before real lookups are enabled.

## Intended workflow

1. Open the app; it handles sign-in only if BOWL.com requires it.
2. Choose a roster file, or use **Single lookup** for one bowler by name or
   membership ID.
3. Click **Look Up Averages**.
4. Pick the right person only when the app finds more than one match.
5. Click **Save Results** to create the JSON result file.

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

- A runnable Tkinter Windows GUI shell
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
  models.py              Shared member, average, and result types
  services/
    auth.py              Private WebView2 sign-in boundary
    average_selector.py  Composite-average selection rule
    bowl_api.py          Member-search and average API boundary
    exports.py           Results and issues CSV output
tests/                    Unit tests
docs/                     Requirements, architecture, and discovery notes
```

## Next milestones

1. Finish the manual-average review workflow and complete independent
   break-testing before merging it to `main`.
2. Confirm BOWL.com/USBC terms and acceptable request volume before broader use.
3. Test signed-out, expired-session, rate-limit, and unexpected-response behavior
   against the real endpoints.
4. Complete the final release checklist on the packaged Windows build, especially
   privacy, process cleanup, memory, and large-roster checks.
5. Package a signed or clearly identified portable Windows executable.
6. Define the acceptance and release criteria for promoting the experimental
   review workflow to a normal release.

See [`docs/requirements.md`](docs/requirements.md) for acceptance criteria and
[`docs/api-notes.md`](docs/api-notes.md) for what is known versus still unknown.
Before a build is considered ready, run the permanent
[`final release checklist`](docs/release-checklist.md), including memory,
process-cleanup, workload, and privacy checks.
