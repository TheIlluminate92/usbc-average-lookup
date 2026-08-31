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

The app never asks for or stores a BOWL.com password. Authentication uses a
user-selected Microsoft Edge or Google Chrome session that supports the site's
normal login and MFA flow. **Sign out** clears the session held by the app.

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
  "schemaVersion": 1,
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

The sign-in flow opens the selected Microsoft Edge or Google Chrome browser and
waits for the genuine BOWL.com site to establish an authenticated API session.
The session token is held in memory and is never written to application logs or
configuration.

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
    auth.py              Browser sign-in boundary
    average_selector.py  Composite-average selection rule
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
