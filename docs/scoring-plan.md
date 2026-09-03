# Scoring, matchups, and standings plan

## Implemented scoring foundation

Each league season can store permanent weekly score sheets. A week has a unique
week number inside the league, optional date and label, a frozen games-per-player
count, and Draft or Final state.

Creating a week snapshots every active Regular registration that currently has
a team. Each line freezes:

- registration/player identity when applicable;
- displayed player and team names;
- roster role;
- team and lineup order;
- entering average;
- handicap.

Current roster moves, renames, withdrawals, or rule changes do not rewrite
prior weeks.

## Game states and calculations

Every player game is stored independently:

| State | Scratch pins | Counted pins |
| --- | --- | --- |
| Bowled | Entered score from 0–300 | score + frozen/currently recalculated player handicap |
| Blind | max(entering average − blind penalty, 0) | blind scratch + handicap |
| Absent | no scratch score | 0 |
| Vacancy | league vacancy score | vacancy score + vacancy handicap |
| Not entered | no scratch score | 0; prevents finalization |

Player handicap is:

```text
floor(max(handicap base - entering average, 0) × handicap percentage)
```

Team scratch and counted totals are derived by game from all score lines
assigned to that team. Team totals are not independently editable.

## Weekly roster adjustments

A draft week can add:

- a league-wide substitute;
- a team substitute;
- another registered player acting as an alternate;
- a previously removed regular;
- a vacancy.

The player is assigned to a team only for that score sheet; the season roster
does not change. Re-adding a removed player preserves the registration's Regular
or Substitute role.

Removing an unentered row asks for confirmation. Removing a row with saved
games requires a reason and logs one removal change per entered game.

## Finalization and corrections

A score sheet cannot be finalized when it is empty or contains Not entered
games. A Final sheet is read-only.

Reopening Final → Draft requires a reason and adds a session-state change to the
log. First-time game entry does not require a reason. Changing a previously
entered status, score, counted value, entering average, or handicap requires a
reason and stores before/after values.

The change log retains:

- session, score line, and game references where applicable;
- player/team display snapshots;
- old and new state;
- old and new scratch/counted pins;
- old and new entering average/handicap;
- reason and timestamp.

## History

The combined score-sheet and correction history is accessible from:

- Scores → History & corrections;
- All leagues → Score history;
- Teams → Score history.

League history can filter to a team. Team history includes weeks with score rows
for that team. Current rows use a fixed team/player order; clickable ascending
and descending team sorting remains planned.

## Current league settings

Each league stores:

- games per session;
- average rule label;
- Standard Composite minimum games;
- multiplier;
- signed pin adjustment;
- nearest/up/down rounding;
- handicap base and percentage;
- blind penalty;
- vacancy score.

The rule engine supports source priority and raw/adjusted league activities,
but only the verified Standard Composite value is currently saved on a
registration and offered to scoring. Named previous-league average selection is
therefore planned, not implemented.

## Next scoring layer: matchups

The next database/UI change should define an explicit match rather than infer it
from the order of teams on a score sheet.

Proposed records:

- schedule/week reference;
- left and right team;
- lane or pair assignment;
- scheduled date/time when useful;
- matchup state such as Scheduled, In progress, Final, Postponed, or Forfeit;
- optional position-round marker.

Requirements:

- A team appears in at most one normal matchup per league week.
- A bye is explicit.
- Makeup or postponed games keep their original league week while recording the
  actual bowling date.
- Matchups reference score-sheet teams but must preserve historical team names.
- No standings points are awarded from a Draft week.

## Configurable points

Point rules belong to the league season. Open decisions include:

- scratch or handicap comparison;
- points per game;
- points for total series;
- tie handling and half-points;
- forfeit and vacancy behavior;
- whether a minimum legal lineup is required;
- position-round exceptions.

Points should be derived from finalized player/team totals. If a league permits
manual point corrections, they should use the existing reasoned change-log
pattern rather than overwrite the source silently.

## Standings

Planned team standings:

- wins, losses, and ties where applicable;
- game and series points;
- total points and rank;
- scratch and handicap pinfall;
- configurable tie breakers;
- week-by-week audit back to finalized score sheets and matchups.

Planned player statistics:

- games bowled;
- scratch total and average;
- high game and high series;
- handicap high game/series when the league uses them;
- minimum-game eligibility;
- team and league filtering.

Standings should be calculated projections, not independently editable master
values. A correction to a finalized source week should recalculate affected
results after the week is reopened, corrected, and finalized again.

## Recap and score-file integration

Import/export formats remain open until representative center or league files
are available. Future design should:

- keep an immutable copy or checksum of an imported source where practical;
- preview player/team matching before committing;
- preserve unknown columns for troubleshooting;
- reject silent score truncation or duplicate weeks;
- export a human-readable recap as well as any machine interchange format.

The flexible average-lookup parser is not automatically a score-import parser.
Game-score formats need their own explicit schema and validation.

## Decisions still required

- How many rostered scores count when extra bowlers participate.
- Whether absent and blind contributions differ by league.
- Handicap caps and team-vs-player handicap variants.
- Legal-lineup rules, vacancies, and forfeits.
- Pre-bowls, post-bowls, makeup dates, and partial series.
- Substitution rules inside a series.
- Tournament-specific squads, shifts, cuts, and stepladder formats.

## Deliberately deferred

Brackets, side pots, payouts, prize funds, and other money handling remain out
of scope. They require substantially stronger auditing, permissions, and
operator safeguards than ordinary score tracking.
