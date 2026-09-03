# Focused bug hunt: 0.7 alpha4

Scope: player/team deletion and archiving, identity carry-over, roster changes,
historical score access, persistence, and existing scheduling/standings regressions.

## Findings fixed

- Identity merges could remove a player profile still referenced by score snapshots.
  Such profiles now remain archived, without rewriting historical scores.
- Removed score rows left correction logs without a durable player ID. Schema 6
  backfills IDs where possible and new edits/removals retain them.
- Player-directory refresh discarded the current selection; it now retains it
  when still visible.
- Tournament score-history shortcuts remained league-only despite tournament
  score support; the shortcuts now accept both competition types.
- Archive integration now preserves historical team filters/standings while
  excluding archived records from new score sheets and copied rosters.

## Automated coverage

- Empty record deletion, cancellation, blocked deletion, and archive/restore UI flows.
- Independent dependency checks for registrations (including withdrawn), season
  pools, scores, removed-row correction history, and scheduled matchups.
- Database-level recheck after a stale UI preflight; restart persistence and no
  resurrection after a subsequent save.
- Schema-5 upgrade and backup, including legacy unresolvable correction history.
- Identity merge preserving historical player IDs.
- 200 local players across 20 teams, 19 round-robin rounds, a 200-row score week,
  draft standings exclusion, database integrity and foreign-key checks.
- Full existing regression suite for registration, scoring, scheduling, standings,
  imports, authentication handling, and navigation.

## Limits and follow-up

Local Tk is unavailable on the development machine: real-widget tests run in
Windows CI. Packaged-app visual usability and actual league-operator feedback still
need human testing. No live BOWL.com load test was performed; the 200-player test
does not measure network lookup performance. This was a focused bug hunt, not a
claim that the application is defect-free.

Some older removed-row corrections have no recoverable player ID. Their presence
conservatively blocks player deletion even when the selected player appears unused;
Archive is the safe alternative. Archive does not withdraw a registration, change
past score sheets, or erase schedule history. Restore records before reusing them.

Legal-lineup enforcement, individual awards, elimination advancement, and payouts
remain deferred. Test with a copy of the database before using real league data.
