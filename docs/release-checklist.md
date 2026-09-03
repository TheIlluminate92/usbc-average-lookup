# Release checklist

Run this checklist against the exact packaged Windows ZIP before promoting a
test build. Record the version, commit, tester, Windows version, date, and
database copy used.

## 1. Source and automated checks

- Working tree contains only intended changes.
- Version/tag and release notes agree with `CHANGELOG.md`.
- `python -m ruff check .` passes.
- `python -m pytest` passes.
- `python -m compileall -q src tests` passes.
- `git diff --check` passes.
- Windows CI passes for the release commit and tag.
- The packaged-helper startup check passes.
- GitHub release contains the expected ZIP, size, and SHA-256 digest.

## 2. Clean install and upgrade

- Extract the ZIP into a new empty folder and start the executable from the
  extracted folder.
- Confirm the compact browser-style strip opens on Registration, followed by
  League Manager and Average lookup.
- Open Registration and each League Manager section in another window. Change
  data in one window and verify every open view refreshes.
- Keep two management windows on different leagues and verify their selections
  remain independent.
- Return a detached Registration view and a detached management section to the
  main window; verify the section and league context are restored.
- Open a score-entry dialog, try the same week in another window, and verify the
  second edit is blocked until the first dialog closes.
- Confirm Average lookup remains in the main window and is not falsely offered
  as detachable.
- Confirm the build does not require Python to be installed.
- Confirm existing schema-version 3 data opens unchanged.
- Upgrade a copy of each older supported SQLite schema and verify an adjacent
  `schema-v*-backup.db` is created before the upgrade.
- Start with only a supported `registration-data.json`; verify the imported
  database, original JSON, and `pre-sqlite-backup.json`.
- Attempt to open a deliberately newer/invalid database copy and confirm the
  application reports the problem without replacing it.

## 3. Sign-in and process cleanup

- Complete ten sign-in/sign-out cycles in one app session.
- Cancel by closing the sign-in window; confirm the Sign in button resets.
- Let one sign-in time out and confirm the main app remains usable.
- Close Bowling Manager while sign-in is open.
- After each path, wait ten seconds and confirm no helper or app-owned WebView2
  processes remain.
- Confirm sign-in uses one private app-owned window and does not open Edge,
  Chrome, Brave, `about:blank`, or unrelated helper tabs.
- Confirm sign-out immediately disables online lookup while leaving local
  league/scoring functions usable.

## 4. Authentication privacy

- Inspect the application folder, `%LOCALAPPDATA%\Bowling Manager`, exports,
  temporary test folder, and console/helper output.
- Confirm no password, bearer token, authorization header, cookie, or browser
  storage value is present.
- Close/reopen the application and verify it starts signed out.
- Confirm only known legacy app-owned profiles are removed; normal browser
  profiles remain untouched.

## 5. Input parsing and export

- Import representative CSV, TSV, pipe-delimited, semicolon-delimited, plain
  text, JSON, and `.xlsx` rosters.
- Test combined name, separate first/last names, member-ID aliases, blank IDs,
  text-formatted leading-zero IDs, duplicate names, and empty rows. Document
  that a spreadsheet may lose leading zeroes before import when it stores an
  ID as a number.
- Test an Excel workbook with one meaningful sheet and another with several;
  verify the sheet picker.
- Verify malformed and empty inputs report a useful error without replacing the
  current roster.
- Export Full, Active/ready, Inactive, and Needs-attention subsets.
- Export JSON, Excel, CSV, TSV, and text.
- Confirm row counts, IDs, status, year, games, and notes survive round trips.
- Confirm Excel adds Needs Attention when appropriate.
- Test input beginning with `=`, `+`, `-`, `@`, tab, carriage return, and newline;
  confirm spreadsheet files do not interpret it as a formula.

## 6. Lookup behavior

- Verify name and membership-ID search.
- Verify one active result, no result, multiple active results, inactive-only,
  no eligible average, expired session, HTTP error, malformed response, and
  network failure.
- Resolve several ambiguous rows consecutively with Next issue.
- Correct one name/member ID and confirm completed rows are not rerun or lost.
- Confirm the selected member ID appears in Registration, Players, and Teams.
- Use a very common name and confirm the UI clearly supports member-ID retry
  when the correct person is not in the first ten candidates.
- Save with unresolved rows and confirm the warning/count.
- Add lookup results to the permanent player directory and verify deduplication.

## 7. League, player, and team management

- Create a league season and a tournament.
- Create next year's league with the same name but a new season.
- Archive and restore a workspace.
- Create, copy, and rename teams.
- Copy a team with active regulars and substitutes; verify withdrawn players are
  not copied and existing assignments are not overwritten.
- Create and copy a player pool; link it to a league.
- Edit a central player identity and verify affected averages are invalidated.
- Move a player between teams and confirm every dependent screen refreshes.
- Remove a team assignment and confirm the registration and player remain.
- Change Regular ↔ Substitute and test team-specific and league-wide pools.
- Double-click leagues, teams, and players; verify relationship Back/Forward in
  both directions.

## 8. Registration

- Register one bowler to an existing team while signed out.
- Add a team and register another bowler.
- Register a whole pasted team.
- Register one bowler into several leagues with different existing teams.
- Register one bowler into several leagues while creating a new team in one.
- Force a duplicate target and verify the entire multi-league operation rolls
  back, including pending new teams.
- Withdraw and restore a registration.
- While signed in, enter enough bowlers to keep both verification workers busy;
  confirm entry remains responsive and the group counter completes accurately.

## 9. Average and handicap rules

- Test minimum-games qualification.
- Test multipliers such as 0.9, signed pin adjustments, and nearest/up/down
  rounding.
- Test handicap base and percentage, including an average above the base.
- Test blind penalty and vacancy score.
- Confirm settings belong only to the selected league season.
- Confirm the UI does not imply that prior-league activity is a selectable
  source yet.

## 10. Weekly scores and history

- Create a week and verify only active team-assigned regulars are snapshotted.
- Verify player/team names, role, entering average, handicap, and game count do
  not change after later roster/rule edits.
- Enter Bowled, Blind, Absent, Vacancy, and Not entered states.
- Confirm bowled scores outside 0–300 are rejected.
- Add a substitute to a team for one week without changing the roster.
- Remove an unentered regular row and add it back; verify it remains Regular.
- Add and remove a scored row; verify a reason is required and logged.
- Confirm scratch and handicap team totals equal the sum of player games.
- Confirm deterministic team/player ordering and filter history to one team.
- Confirm an incomplete week cannot be finalized.
- Finalize a complete week and verify it is read-only.
- Reopen with a reason, correct a score with a reason, re-finalize, and inspect
  every change-log field.
- Open the same history from Scores, League management, and Team management.

## 11. Persistence and backup

- Restart after player, team, league, registration, rule, score, and correction
  changes; verify every record returns.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`; expect `ok` and no
  foreign-key rows.
- Back up and restore the database while the application is closed.
- Verify copying only the portable program folder does not falsely appear to
  copy the database.
- Verify unsupported/newer databases and failed writes do not produce a silent
  empty replacement.

## 12. Workload and resources

- Normal workload: build/import a representative four-league data set totaling
  up to 200 bowlers, including duplicate names and multi-league players.
- Stress parser/UI: load a 1,000-row roster, clear it, then load another.
- Do not run an unapproved 1,000-member live BOWL.com lookup merely for stress
  testing; network volume must remain authorized and conservative.
- Record main-app memory and Windows handle count after one idle minute.
- Repeat ten sign-in/sign-out cycles and the normal 200-bowler local workflow;
  let the app idle again.
- Memory must settle within 50 MB of the starting value and not grow steadily.
- Handles must settle within 50 of the starting value and not grow steadily.
- Idle CPU should remain near 0% with no repeated network activity.

## 13. Documentation and release page

- README download link and current limitations are accurate.
- User guide labels match the packaged UI.
- Requirements mark implemented and planned scope honestly.
- API notes contain no credentials or identifying member data.
- Security policy documents unencrypted local personal data and unsigned builds.
- Changelog lists the release's user-visible changes and migration impact.
- Release notes identify the build as pre-alpha/unofficial and link to the
  documentation.

## Release blockers

Do not promote a build with:

- data loss, partial multi-record writes, failed integrity checks, or missing
  migration backups;
- silent member matching or score-history rewrites;
- leaked credentials/session material;
- an orphaned helper/WebView2 process after cleanup;
- steadily increasing idle memory/handles;
- inaccurate totals or correction history;
- a failed Windows CI/package job;
- documentation claiming an unimplemented source, standings feature, or public
  BOWL.com support.
