# Changelog

## 0.4.3 — Bug fixes and About

- Added About with the installed version, creator credits, acknowledgments, and project link.
- Corrected names now update exported name fields; official multi-part surnames stay intact.
- Duplicate import choices recognize saved names and aliases.
- Split-name imports retain middle names/initials; one-column USBC-ID imports work correctly.
- Damaged Excel workbooks produce a readable error.
- Export and backup paths cannot overwrite the live database or its journal files.
- Fixed overlapping sign-out/sign-in cleanup and stale refresh authentication errors.
- Lint and all 128 tests passed on Windows for the release.

## 0.4.2 — Color theme

- Added a consistent navy and teal theme across the directory and dialogs.
- Added readable status colors and clearer primary and delete actions.

## 0.4.1 — Directory and export fixes

- Added deletion of saved bowlers from the directory and details window.
- Added state/ZIP search refinement for common names and retained saved-ID refresh.
- Kept export controls accessible on smaller screens.

## 0.4.0 — Persistent Average Assistant

- Permanent SQLite bowler directory with migrations and online backups.
- Saved-ID refresh, bounded parallel collection, incremental status, and cancellation.
- Full returned composite history, normalized member/league data, sanitized snapshots.
- Searchable database UI with member details, revisions, and duplicate resolution.
- Quiet private BOWL.com sign-in cancellation from the manual-registration branch.
- BTM26+ CSV with export-time average rules and a preview; generic CSV/XLSX/JSON.
- League-manager features preserved separately, without merging them into this app.
