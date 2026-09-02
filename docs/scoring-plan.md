# Scoring and standings plan

## Implemented scoring foundation

Each league season can keep any number of permanent weekly score sheets. A
score sheet freezes the league's game count and each line's player name, team
name, role, entering average, and handicap. Later roster, identity, team-name,
or average-rule edits therefore do not rewrite historical weeks.

Each player game is stored independently with one of these states:

- `Bowled` with a scratch score from 0 through 300
- `Absent` with no counted pins
- `Blind` using the frozen entering average minus the league blind penalty
- `Vacancy` using the league vacancy score
- `Not entered` while the score sheet remains incomplete

Team scratch and handicap totals are derived from the player-game records. They
are not separately editable values. A league-wide or team substitute can be
placed on a team for one score sheet without changing the season roster.

History can be entered from the league, from one team, or from the Scores tab.
League history can be narrowed to one team, while team history shows only weeks
where that team has score rows. The relationship browser navigates league →
team → player and player → team/league with Back and Forward controls.

First-time score entry does not require a note. Changing an entered score or
its average/handicap calculation requires a reason and writes the before/after
values to an append-only change log. Removing a scored line and reopening a
final week also require a reason. A final week cannot be edited until reopened.

The SQLite schema upgrade creates a one-time pre-upgrade database copy before
adding score tables. Score history is deliberately stored as snapshots and is
not deleted or regenerated when the current registration directory is saved.

## League settings

The first scoring rule connects the verified standard composite average to a
league-specific minimum-games requirement, multiplier, pin adjustment, and
rounding rule. Each league also owns its games-per-night, handicap base and
percentage, blind penalty, and vacancy score.

The average-rule engine already supports league-activity candidates, but the
lookup workflow does not yet retain those raw rows. Selecting a named previous
league average must therefore wait until raw league activities are persisted;
the UI must not imply that source is active before it is actually available.

## Next scoring layers

### Match schedule and points

- Define which two teams meet each week and their lane/pair assignment.
- Configure the number of points available per game and series.
- Allow scratch or handicap comparison, ties, forfeits, and position rounds.
- Calculate match points from finalized score sheets only.
- Keep manual point corrections in the same reasoned change-log model.

### Standings and leaderboards

- Team wins, losses, ties, total points, and season rank.
- Player high game, high series, scratch average, and handicap results.
- Minimum-game eligibility and configurable tie breakers.
- Recalculate projections from finalized weeks while retaining the source
  scores and corrections that produced them.

### Later decisions

- Whether absent and blind contributions are the same in each league.
- Whether handicap is capped and whether it applies per player or per team.
- Roster-size limits and how many scores count when extra bowlers participate.
- Makeup games, pre-bowls, postponed weeks, and partial-team forfeits.
- Export/import formats once representative recap sheets are available.

Brackets, side pots, payouts, and other money handling remain deliberately out
of scope until scoring and standings are stable.
