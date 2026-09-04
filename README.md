# Average Assistant

A standalone Windows bowler database for BOWL.com member data, average history,
and BTM26+ exports. Bowlers stay saved between runs; import new people, refresh
when needed, then choose the stored average to export.

## Download and start

**[Download the latest Windows release](https://github.com/TheIlluminate92/usbc-average-lookup/releases/latest)**

1. Download `Average-Assistant-<version>-Windows.zip` from the release's **Assets**.
2. Extract the entire ZIP to a folder. Keep `_internal` beside the application.
3. Run `USBC-Average-Lookup.exe`. No Python installation is needed.
4. Add or import bowlers, then sign in to BOWL.com when you want to refresh data.

Windows and the Microsoft Edge WebView2 Runtime are required. A BOWL.com account
is needed for authenticated refreshes; saved records and exports work offline.

**Updating:** close the app and extract the new release into a new folder.
Your saved bowler database is reused automatically. Use **Back up** in the app
before updating if you want a separate copy.

See the [changelog](CHANGELOG.md) for changes. Older **Bowling Manager** alpha
releases are historical league-manager builds; use **Average Assistant** for this app.

## Everyday workflow

1. Open the app to your saved bowler directory.
2. Add a bowler or import CSV, XLSX, TSV, TXT, or JSON. Existing USBC IDs reuse
   saved records. Name-only duplicates are reviewed before reusing a confirmed member.
3. Sign in to BOWL.com in the private sign-in window.
4. Refresh selected, visible/filtered, or all bowlers. Progress appears as each
   result is saved. Cancel stops further work and retains completed refreshes.
5. Double-click a bowler for member details, all stored composite averages,
   revisions, league activity, and sanitized API snapshots.
6. Export selected, visible, or all bowlers. Choose Composite, League, or Adjusted
   league data; latest/highest/specific year/type, hand, minimum games, or a manual
   stored record per bowler. Review missing averages before saving.

## BTM26+ CSV

The dedicated export writes these seven columns:

```text
First Name,Middle Initial,Last Name,Gender,Book Average,Book Games,USBC ID Number
```

In BTM's CSV import wizard, skip **1** header line and map the columns. Map
**Middle Initial** to BTM's **Middle Name** field. The confirmed import field list
has no team field: assign teams inside BTM after importing. See
[CDE's import guide](https://support.cdesoftware.com/kb/a3070/import-from-file.aspx).

Year values are BOWL.com's season-ending year: **2025 = 2024–2025**. Average and
games always come from the same selected stored record. Missing averages default
to blocking export; explicitly choose Blank or Skip to proceed. Generic CSV/XLSX
include year, classification, source, association and status context; JSON is also
available. Export never deletes or changes saved history.

## Saved data

The permanent database is stored at:

```text
%LOCALAPPDATA%\Average Assistant\bowlers.sqlite3
```

It retains normalized member identity, association/state, gender, middle initial,
membership dates/type/flags, all returned composite records and changes, normalized
league activity, and sanitized API snapshots. No bearer tokens or authorization
headers are saved. Unrelated name-search candidates are not saved as bowler snapshots.

Use **Back up** for a consistent standalone copy, including completed refreshes.
To restore, close the app and replace the database with that backup. Database schema
upgrades run automatically in transactions; newer unsupported schemas are rejected.
Window size, search/filter/sort, and the last export folder are remembered.

## Run from source

Requires Python 3.11+ on Windows and the Microsoft Edge WebView2 Runtime.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m usbc_average_lookup
```

Closing the BOWL.com sign-in window or clicking Cancel sign-in returns quietly to
the app. The directory and exports work offline. A new sign-in is required after
restarting. HTTP 401/403 or rate limits stop the current batch; sign in again or
wait before retrying. A failed refresh preserves the last successful data.

## Development and verification

```powershell
python -m ruff check .
python -m pytest
```

Windows CI includes desktop integration tests for search, dialogs, export rules,
progress updates, and sign-in cancellation. Service tests cover migrations,
identity reuse, retained history, pagination, sanitization, cancellation, and
export formats. Live BOWL.com sign-in and BTM import require operator acceptance.
The Windows build workflow packages the application and private sign-in helper.

The implementation is split into SQLite storage (`database.py`), collection and
export services (`services/`), and desktop presentation (`database_app.py`, `ui.py`).
See [database design](docs/database-design.md) for schema and behavior details.

## Scope

This app does not contain league registration, scheduling, scoring, or standings.
That development is preserved separately in a private league-manager repository.

Harvesting currently covers the verified member, composite-average, and
league-activity endpoints. `relatedaverages` still needs a sanitized request and
response sample before integration. Older 0.3 design documents are retained for
historical context; the database design above describes the current app.

## Help and bug reports

[Open an issue](https://github.com/TheIlluminate92/usbc-average-lookup/issues/new/choose)
with your app version (shown in **About**), Windows version, what you did, and
what happened. Include a small fictional example when an import or export fails.
Remove names, member IDs, and other personal details from screenshots. Do not
upload your bowler database, account credentials, or browser captures. See
[SECURITY.md](SECURITY.md) for handling sensitive reports.

## Credits

Created by **Erik Boettcher (TheIlluminate92)**, with development assistance from
OpenAI Codex. Open **About** in the app for the version, project link, and credits.

Member information and averages come from BOWL.com / USBC. BTM is Bowling
Tournament Manager by CDE Software. Average Assistant uses Python, Tcl/Tk, SQLite,
openpyxl, pywebview, Microsoft Edge WebView2, and PyInstaller. Thanks to their
maintainers and contributors, and to the bowlers who help test this app.
