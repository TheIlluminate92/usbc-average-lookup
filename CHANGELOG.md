# Changelog

This project is pre-alpha. Version labels identify test builds and may include
database/UI changes that are not yet stable public contracts.

## Unreleased

## v0.7.0-alpha.4 — 2026-09-03

- Added player/team Archive, Restore, Show archived, and confirmed Delete actions.
- Blocked deletion when registrations, season-pool entries, score sheets, score
  history, or scheduled matchups reference the record; recheck inside a transaction.
- Added schema 6 with pre-upgrade backups, archive flags, and durable player IDs
  in score correction history, including removed score rows.
- Preserved old player profiles as archived when identity merges would otherwise
  orphan historical score references.
- Preserved player selection on refresh, enabled tournament history shortcuts,
  and retained archived teams in historical score filters and standings.
- Blocked archived players from new registrations/team changes and skipped them
  when copying rosters. Archive does not withdraw existing registrations.
- Added deletion, migration, archive/restore, real-widget, and 200-player regression
  coverage. Live BOWL.com load testing and human usability testing remain separate.

## v0.7.0-alpha.3 — 2026-09-03

- Connected schedule rounds to explicit, unique score-week links with Open scores.
- Added a pop-out-capable Standings tab with configurable scratch/handicap,
  game/series points, ties, ranking, and pinfall tie breakers.
- Snapshotted scoring rules per link and logged link/unlink history.
- Excluded Draft, unlinked, BYE, postponed/cancelled, and unsupported forfeit
  results; reopening and refinalizing scores recalculates standings.
- Blocked finalization when a scheduled opponent has no score row.
- Enabled round-robin tournament score sheets as well as league weeks.
- Fixed overlapping lane-pair assignments and shared refresh after score writes.
- Added schema version 5 with an automatic pre-upgrade version-4 backup.
- Queued a focused bug hunt next; legal lineups, individual awards, elimination
  advancement, and payouts remain deferred.

## v0.7.0-alpha.2 — 2026-09-03

- Shortened management tabs to Home, Teams, Schedule, Scores, Rules, Players,
  and All leagues, preserving new-tab and pop-out navigation.
- Clarified compact actions including Build schedule, Change lanes, Add bowler,
  Roster, Register team, Choose leagues, and Add existing player.
- Added hover and keyboard-focus hints to selected compact controls.
- Kept withdrawal, pool removal, and score finalization explicit; withdrawal
  labels distinguish leagues from tournaments.
- Updated the user guide and release checklist; added navigation and hint tests.
- No database migration: SQLite remains at schema version 4.

## v0.7.0-alpha.1 — 2026-09-03

- Added configurable Round robin, Single elimination, and Custom/manual
  competition formats. Round-robin generation is the first implemented format.
- Added a Schedule & lanes workspace with automatic full round-robin pairing,
  rotating lane pairs, explicit BYEs, week/round navigation, and manual lane
  corrections.
- Added permanent round and matchup snapshots so later team renames do not
  rewrite an existing schedule.
- Added ascending/descending Team heading controls to both the player score
  sheet and team totals.
- Upgraded SQLite to schema version 4 with an automatic version-3 backup.
- Kept standings, elimination generation, prize calculations, side brackets,
  and payment handling deliberately out of this first 0.7 slice.

## v0.6.0-alpha.5 — 2026-09-03

- Added right-click Open in new tab and Pop out into separate window actions
  to every League Manager subtab while preserving its selected league.
- Reduced the Scores & history controls from three rows to two and grouped
  week controls separately from score-sheet row actions.

## v0.6.0-alpha.4 — 2026-09-03

- Expanded Scores & history by removing its duplicate league selector and
  oversized heading, tightening the controls, and adding a draggable split
  between the score sheet and team totals.
- Renamed Leagues & seasons to All leagues and clarified that it is the master
  season list while League home is the dashboard for the selected league.
- Removed the permanent New tab and Open view in new tab controls. Workspace
  tabs now expose new-tab, pop-out, and close actions from their right-click
  menu, including moving an extra tab into its own window.
- Compacted every League Manager section and removed the duplicate league
  selector from Teams & roster; the shared workspace selector is now the only
  league selector in management.
- Combined score-sheet history and the correction log into one window with
  Score sheets and Corrections tabs.
- Moved secondary team and season commands into More actions menus while
  keeping the frequent create, roster, edit, and archive actions visible.

## v0.6.0-alpha.3 — 2026-09-03

- Preserved a resolved inactive-member result when only the player's team or
  roster role changes.
- Expanded Teams & roster into a full-size team list and moved each team's
  regulars and substitutes into a double-click roster window.
- Replaced League home's Register bowler shortcut with a primary Create team
  action.
- Made extra workspaces browser-like in-app tabs with close controls,
  middle-click/right-click closing, independent league context, and optional
  separate windows.
- Kept score correction dialogs open when a required reason is missing and
  added an inline validation footer without removing Cancel.

## v0.6.0-alpha.2 — 2026-09-02

- Added **Return to main window** to detached Registration and League Manager
  views.
- Reattaching restores the detached view's selected management section and
  league/tournament context in the main window.

## v0.6.0-alpha.1 — 2026-09-02

- Replaced the oversized header with compact browser-style workspace chrome.
- Kept Registration first and added a New window menu plus tab context menus.
- Added one persistent league/tournament context shared by registration, team,
  scoring, overview, and rules views.
- Added League home and Rules & setup management views.
- Renamed management sections around operator tasks instead of storage types.
- Added synchronized Registration and League Manager windows with independent
  league selections.
- Prevented two windows from opening score-entry dialogs for the same week at
  the same time.
- Added store change notifications so every open management view refreshes
  after a successful write.
- Kept the SQLite schema at version 3.
- Reconciled all GitHub documentation with the current application and added a
  full operator user guide.

## v0.5.0-alpha.2 — 2026-09-02

- Moved Registration to its own top-level workspace.
- Added atomic multi-league registration with per-league existing/new team
  choices.
- Changed player/team/league double-click to relationship navigation while
  keeping edits on explicit buttons.
- Centralized roster-change refreshes across registration, player, team,
  league, and scoring views.
- Added an obvious score-sheet path to restore a removed player or add a
  substitute.
- Preserved a restored player's original Regular/Substitute role.
- Kept the SQLite schema at version 3; no database migration was required.

## v0.5.0-alpha.1 — 2026-09-02

- Added permanent weekly league score sheets.
- Added individual game states and derived scratch/handicap team totals.
- Added league scoring/handicap settings.
- Added weekly substitutes and vacancies.
- Added Draft/Final behavior, reasoned corrections, and a persistent change
  log.
- Added league/team score history and relationship navigation.
- Upgraded SQLite to schema version 3 with pre-upgrade database backups.

## v0.4.0-alpha.4 — 2026-09-02

- Hardened lookup and ambiguous-member review workflows.
- Kept reviewed player/member identities synchronized across management views.
- Improved sign-in cancellation and issue-review reliability.

## v0.4.0-alpha.3 — 2026-09-02

- Added reusable player and team workflows across league seasons.
- Added pulling existing players and copying prior teams/rosters.
- Added average-lookup result import into the permanent player directory.

## v0.4.0-alpha.2 — 2026-09-02

- Fixed reviewed member IDs so the shared player identity stays synchronized.
- Strengthened duplicate player identity handling.

## v0.4.0-alpha.1 — 2026-09-02

- Began publishing tagged portable Windows test builds.
- Added GitHub release ZIP automation and packaged sign-in-helper verification.

## Earlier foundation

- Added the manual Registration Desk.
- Added League, Player, and Team management tabs.
- Added seasonal player pools, regular/substitute roles, and league-wide
  substitutes.
- Migrated registration storage from JSON to schema-versioned SQLite.
- Added a private WebView2 BOWL.com sign-in helper.
- Added CSV/TSV/text/JSON/Excel lookup input and multi-format output.
- Added fixture-tested member search, composite average selection, league
  activities, and a configurable average-rule engine.
