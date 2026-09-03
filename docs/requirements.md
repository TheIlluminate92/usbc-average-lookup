# Product requirements and scope

## Product goal

Provide one nontechnical league operator with a local Windows application that
can manage roughly four weekly leagues, changing seasonal rosters, occasional
weekend tournaments, verified bowler averages, and permanent game-by-game
scores. The normal upper bound is approximately 200 distinct bowlers.

The application should feel substantially friendlier than traditional bowling
tournament software while keeping historical records stable and auditable.

## Current release stage

The current line is v0.6 pre-alpha. It is suitable for controlled testing with
small real leagues, not broad public distribution. The product is manual-first:
league management and scoring work offline, while BOWL.com sign-in is optional
and used only for average verification.

The release is a portable, unsigned Windows folder. Data is local to the
Windows user profile in a schema-versioned SQLite database.

## Core domain requirements

### Player identity

- Store one permanent player identity with name and optional USBC member ID.
- Reuse that identity across any number of league seasons and tournaments.
- Keep different people with the same name separate when member IDs differ.
- Do not silently merge ambiguous same-name players.
- Propagate a reviewed member ID to every screen using the shared player
  identity.
- Invalidate verified averages when a player identity materially changes.

### Player pools

- Keep optional year/season player pools separate from the permanent directory.
- Allow a pool to be copied forward and edited without changing prior years.
- Allow a league or tournament to link to one pool.
- Add new registrations to the linked pool without duplicating entries.

### League seasons and tournaments

- Treat each league season as an independent competition, even when the league
  name repeats next year.
- Store name, season/year, and League or Tournament type.
- Archive and restore old workspaces without deleting history.
- Keep teams, registrations, rules, and scores scoped to their competition.
- Prevent a team from being assigned across competitions.

### Teams and rosters

- Allow competition-specific team creation and rename.
- Copy a team from a prior competition with an optional active-roster copy.
- Support Regular and Substitute roster roles.
- Support team-specific substitutes and an unassigned league-wide substitute
  pool.
- Move players between teams without deleting the league registration or
  permanent identity.
- Filter Team management by league or tournament.
- Refresh registration, player, team, league, and scoring views after any
  assignment change.

### Registration

- Register one bowler manually with optional member ID and team.
- Create a team before registration or as part of multi-league registration.
- Register one bowler into several leagues/tournaments in one operation with a
  separate team assignment for each.
- Make multi-league registration atomic: no partial players, teams, pool
  entries, or registrations if any target fails.
- Register a pasted team roster atomically.
- Reject a duplicate player registration within the same competition.
- Allow withdrawal/restore separately from team removal.
- Show a visible group counter for total, ready, and needs-attention entries.

### Relationship navigation

- Double-clicking a league, team, or player opens related records.
- Navigate league → teams → players and player → teams/leagues.
- Provide Back and Forward history.
- Keep editing on explicit labeled actions rather than overloading double-click.

### Management workspace

- Keep one current league/tournament selection synchronized across management
  and registration views.
- Provide a league home work queue plus task-oriented Teams & roster, Scores &
  history, Rules & setup, Player directory, and All leagues sections.
- Refresh every open management window after a successful domain write.
- Allow Registration and a selected management view to open in additional
  windows with an independent league selection.
- Allow a detached view to return its current section and league selection to
  the main window.
- Prevent simultaneous score-entry dialogs for the same weekly score sheet.
- Keep Average lookup in the main window until its UI state is separated from
  the application shell.

## BOWL.com lookup requirements

### Authentication

- Open the genuine BOWL.com page in a private application-owned WebView2
  helper.
- Never present an application-owned password field.
- Never write passwords, bearer tokens, cookies, or browser storage to the
  database, exports, configuration, diagnostics, or source control.
- Keep the temporary bearer token in memory only.
- Sign out, closing the app, cancellation, and timeout must terminate the helper
  and return the main window to a usable state.
- Distinguish signed out, signed in, and expired session.

### Search and matching

- Search by name or member ID using the observed BOWL.com JSON operations.
- Use membership ID instead of name when supplied.
- Never silently choose among multiple active candidates.
- Show candidate name, member ID, active state, association/state, and
  membership period when available.
- Allow fixing one row without rerunning completed rows.
- Allow Next issue navigation through unresolved results.
- Surface safe, actionable states for not found, inactive, no average, expired
  session, and API/schema/network errors.
- Treat the current first-page/ten-candidate name search as a known limitation;
  common names should use member ID until pagination is implemented.

### Average selection

- Select the newest composite-average record where `sport == false`,
  `challenge == false`, and `games > 0`.
- Preserve the returned average, ending year, and games.
- Describe it as Standard Composite Average.
- Do not imply that raw prior-league averages are selectable until those rows
  are retained on the registration.

### Request behavior

- Keep network work off the Tkinter UI thread.
- Registration uses a fixed two-worker queue so one ambiguous result does not
  stop data entry and request bursts remain bounded.
- Full roster lookup may run in a background thread but currently processes
  rows sequentially.
- Detect invalid response envelopes, invalid records, invalid pagination, and
  HTTP authentication failures rather than producing guessed results.

## Import and export requirements

### Input

- Accept CSV, TSV, delimited text, JSON, and `.xlsx`.
- Recognize comma, tab, pipe, and semicolon delimiters.
- Recognize common combined-name, separate first/last-name, and membership-ID
  headings.
- Accept `Name (1234-567890)` and one-name-per-line text.
- Preserve membership IDs as text, including hyphens and leading zeroes, when
  the source stores them as text. A spreadsheet that has already converted an
  ID to a number may already have discarded its leading zeroes.
- Ignore empty rows and reject files with no usable bowlers.
- Ask which worksheet to use when an Excel file has several non-empty sheets.
- Do not support legacy `.xls` unless representative files justify it.
- Keep formats extensible because final league/tournament file shapes remain
  unknown.

### Lookup output

- Export JSON, Excel, CSV, TSV, or plain text.
- Offer Full, Active/ready, Inactive, and Needs-attention subsets.
- Default to Full so unresolved players are not silently omitted.
- Show how many rows will be written.
- Confirm before saving a full roster with unresolved rows.
- Preserve name, member ID, average, year, games, status, notes, active state,
  and association where the format allows.
- Give Excel a Results sheet and a Needs Attention sheet when applicable.
- Prevent imported or remote text from becoming a spreadsheet formula.
- Allow current lookup results to be merged into the permanent player list.

## League average and handicap requirements

- Store rules per league season, not globally.
- Current selectable source is the verified Standard Composite value on the
  registration.
- Apply optional minimum-games qualification, decimal multiplier, signed pin
  adjustment, and nearest/up/down rounding.
- Store games per session, handicap base, handicap percentage, blind penalty,
  and vacancy score per league.
- Calculate player handicap as
  `floor(max(base - average, 0) × percentage)`.
- Freeze the entering average and handicap on each weekly score line.

## Weekly scoring requirements

- Create one permanent session per league/week number with optional date and
  label.
- Copy active Regular registrations with team assignments into the new sheet.
- Snapshot player name, team name, roster role, entering average, handicap,
  lineup order, and games per player.
- Add a registered player to a team for one week without changing the season
  roster.
- Restore a removed regular through the same Add player workflow while
  preserving the original roster role.
- Add vacancy rows.
- Store each game independently as Bowled, Blind, Absent, Vacancy, or Not
  entered.
- Validate bowled scores from 0 through 300.
- Derive team scratch and handicap totals from player games; never store an
  independently editable team total.
- Present score rows in a deterministic team/player order.
- Keep score history accessible from Scores, League management, and Team
  management.

### Finalization and audit

- Do not finalize an empty sheet or a sheet with Not entered games.
- Prevent edits to a final sheet until it is reopened.
- Require a reason to reopen a final sheet.
- First-time entry does not require a reason.
- Require a reason when changing a previously entered score, calculated value,
  or entering average.
- Require a reason before removing a row that contains entered games.
- Append before/after values, identity snapshots, reason, and timestamp to the
  change log.
- Preserve prior history when current players, teams, rosters, or rules change.

## Storage and reliability requirements

- Use a local SQLite database at
  `%LOCALAPPDATA%\Bowling Manager\bowling-manager.db`.
- Use transactions for every logical write.
- Enforce primary keys, foreign keys, uniqueness, and enumerated state checks.
- Leave unreadable or newer unsupported databases unchanged.
- Import legacy schema-version 1 or 2 JSON through a temporary verified
  database, preserving the source and a separate backup.
- Before a SQLite schema upgrade, create one backup per old schema version using
  SQLite's backup API.
- Keep score transactions independent from full registration-store rewrites so
  normal roster saves do not regenerate score history.
- Document that the database is local and unencrypted by the application.

## User experience requirements

- Use plain bowling language and avoid exposing endpoints, tokens, SQL, or
  request settings.
- Keep normal actions available while signed out except BOWL.com lookup.
- Prefer explicit buttons for destructive or editing actions.
- Preserve selected league/team where practical during refresh.
- Support keyboard-first score entry and checkbox-style multi-selection in a
  future UI pass; current behavior is functional but not yet the target level
  of friendliness.
- Add clickable ascending/descending team sorting to score sheets and history
  in a future UI pass.
- Remember useful filters and last-selected context in a future UI pass.

## Current non-goals

- Shared web service, cloud sync, multi-user login, or simultaneous editing.
- Mobile or QR self-registration in the current milestone.
- Brackets, side pots, payouts, prize accounting, or other money handling.
- Automatically choosing an ambiguous member.
- Scraping rendered BOWL.com HTML.
- Recalculating BOWL.com's Standard Composite from league rows.
- Matchups, lane assignments, points, standings, and leaderboards until the
  scoring foundation is validated.

## Planned next layer

1. Real-world workflow testing with four weekly leagues, weekend tournaments,
   and up to 200 bowlers.
2. Checkbox-style multi-league registration, remembered filters, and a more
   keyboard-friendly scoring grid.
3. Match schedule, lane/pair assignments, configurable game/series points,
   ties, forfeits, and position rounds.
4. Standings and player/team leaderboards derived from finalized score sheets.
5. Persisted raw league activities and league-selectable prior-average sources.
6. Recap-sheet import/export after representative files are available.

## Acceptance criteria for the current test release

- All automated tests and code-quality checks pass on Windows CI.
- A packaged sign-in helper starts and returns a structured response.
- Existing SQLite data opens without loss and schema backups are created when
  required.
- Moving a player between teams refreshes all dependent screens.
- Reviewed member IDs appear in permanent player and team views.
- Multi-league registration either saves every target or saves none.
- A removed regular can be added back to a draft score sheet as a Regular.
- Score corrections and final-week reopening require and retain reasons.
- Input and export round trips preserve member IDs as text.
- The packaged application completes the manual checks in
  [release-checklist.md](release-checklist.md), including the 200-bowler normal
  workload and 1,000-row parser/UI stress test.
