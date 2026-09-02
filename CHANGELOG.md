# Changelog

This project is pre-alpha. Version labels identify test builds and may include
database/UI changes that are not yet stable public contracts.

## Unreleased

- Reconciled all GitHub documentation with the current v0.5 application.
- Added a full operator user guide.
- Documented current limits, local-data/privacy boundaries, database backup and
  migration behavior, release checks, and the planned matchup/standings layer.

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
