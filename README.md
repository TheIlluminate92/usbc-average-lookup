# USBC Average Lookup

A small Windows desktop utility for turning a list of bowler names into
reviewed `Name,Average` results using BOWL.com's JSON-backed member search,
composite, league, converted, and rerated-average data.

> [!CAUTION]
> Version 0.4 is an experimental review-workflow branch. The tested 0.3.1
> release remains unchanged on `main` until this workflow is approved.

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
4. Resolve identity problems under **Fixes needed**.
5. Review and explicitly confirm one average for every bowler under **Review
   averages**.
6. Click **Save Results** only after the roster is fully reviewed.

The app never asks for or stores a BOWL.com password. Authentication opens the
real BOWL.com page in a private sign-in window owned by Average Assistant. It
does not open tabs in Edge, Chrome, or Brave. **Sign out** and closing the app
discard the in-memory session; the private window does not retain cookies or
browser storage.
Version 0.3.0 also removes the app-owned browser profiles left by older builds;
it does not touch the user's normal browser data.

## Result states

Every input name receives exactly one visible result:

- `Review required`
- `Found`
- `Not found`
- `Multiple matches`
- `No average`
- `Inactive member`
- `Login expired`
- `API error`

Only explicitly confirmed `Found` rows belong in the clean ready-roster export.
An average returned by BOWL.com remains `Review required` until the operator
confirms it. All other rows are retained with an explanatory note.

## Manual average review

The review queue keeps all average choices returned for each selected member.
Operators can filter by season, configurable minimum games, Standard/Sport/
Challenge type, league, center/association, and rerate inclusion. Choices can
be sorted by newest, highest average, or most games. Filters never delete the
underlying choices.

The app may preselect the newest Standard Composite Average to reduce clicking,
but it never confirms that selection. Every bowler requires an explicit
confirmation action. Individual review provides **Confirm selected and go to
next**. Bulk review shows one proposed value per bowler but initially selects
nothing. A visible **Use** checkbox column, three-step instructions, and selection
buttons make the batch explicit before one final confirmation. Every unselected
or filtered-out bowler remains in the individual queue. Ready-roster export is
blocked until no review or identity issues remain.

Saving the full roster as JSON creates a resumable review draft. Choosing that
JSON file later restores confirmed averages, unreviewed choices, member details,
and unresolved match candidates. CSV, TSV, text, and Excel remain presentation
exports and do not contain enough structure to resume a review.

## Input formats

The model accepts `.csv` and `.txt` files with comma, tab, pipe, or semicolon
delimiters. A header is optional:

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
  "schemaVersion": 4,
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
      "reviewed": true,
      "status": "Found",
      "notes": null
    }
  ]
}
```

## What is included

- A runnable Tkinter Windows GUI shell
- Domain models for members, composite averages, and lookup outcomes
- Required per-bowler review with configurable minimum-games and average filters
- Composite, league, converted, and rerated/adjusted average models
- Browser-based BOWL.com sign-in through the genuine site; passwords are never
  exposed to the application
- JSON export containing every input row, status, average, and notes
- Resumable schema-versioned JSON review drafts
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
    average_options.py   Complete choice filtering and safe suggestion logic
    average_selector.py  Legacy composite-average selection rule
    bowl_api.py          Member-search and average API boundary
    exports.py           Results and issues CSV output
tests/                    Unit tests
docs/                     Requirements, architecture, and discovery notes
```

## Next milestones

1. Record sanitized request URLs, methods, and response shapes for member search
   and composite averages.
2. Test both endpoints while signed out.
3. Confirm BOWL.com/USBC terms and acceptable request volume.
4. Implement browser-based authentication only if anonymous access is not
   available.
5. Add a simple member-choice dialog and automatic retry for temporary failures.
6. Package a signed or clearly identified portable Windows executable.

See [`docs/requirements.md`](docs/requirements.md) for acceptance criteria and
[`docs/api-notes.md`](docs/api-notes.md) for what is known versus still unknown.
Before a build is considered ready, run the permanent
[`final release checklist`](docs/release-checklist.md), including memory,
process-cleanup, workload, and privacy checks.
