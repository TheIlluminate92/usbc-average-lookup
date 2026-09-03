# User guide

This guide describes the current v0.6 pre-alpha Windows application. Labels may
change as the workflow is tested with real leagues.

## Install and start

1. Download `USBC-Average-Lookup-Windows.zip` from the latest test release.
2. Extract the complete `USBC-Average-Lookup` folder. Do not run the executable
   from inside the ZIP.
3. Start `USBC-Average-Lookup.exe`.

The build is portable and has no installer. Windows may warn because the test
build is unsigned.

League data is stored separately from the application folder:

```text
%LOCALAPPDATA%\Bowling Manager\bowling-manager.db
```

Moving or replacing the program folder does not move or erase that database.

## Main navigation, tabs, and extra windows

The compact top strip works like a browser and opens on **Registration**:

- **Registration** — fast day-of or preseason player entry.
- **League Manager** — league home, rosters, scoring, rules, players, and
  historical seasons.
- **Average lookup** — BOWL.com lookup from a roster file or one player.

Right-click **Registration** or **League Manager** to open another tab or pop
the current view into a separate window. Each management tab may remain on a
different league. Right-click an extra tab to move it into a separate window
or close it; its `×` and middle-click also close it. All tabs and windows
refresh from the same database.

Every League Manager subtab also has a right-click menu. Use it to open League
home, Teams & roster, Scores & history, Rules & setup, Player directory, or All
leagues in another top-level tab or a separate window. The new view keeps the
league currently selected in the workspace bar.

The familiar **Ctrl+T** shortcut duplicates the current working view in a new
tab, and **Ctrl+W** closes the selected extra tab. The three permanent tabs are
not closed by Ctrl+W.

Choose **Return to main window** to bring a detached Registration view or its
current League Manager section and selected league back to the main window.

Average lookup remains in the main window. If a weekly score-entry dialog is
already open in one window, another window cannot edit that same score sheet
until the dialog closes.

Sign-in status and the BOWL.com controls share the compact strip. Sign-in is
required only for online lookup; local records and scoring remain usable while
signed out.

## Create a league season or tournament

1. Open **League Manager** and **All leagues**.
2. Select **New league or tournament**.
3. Enter the name, season/year, and type.

Treat each league season as a separate workspace. For example, `Monday Misfits
2025-26` and `Monday Misfits 2026-27` are different records. This keeps earlier
teams, rosters, and score history unchanged.

The screen also supports:

- editing the selected workspace;
- archiving or restoring it;
- adding or copying a team;
- registering a new player or pulling one from the permanent directory;
- linking a reusable player pool;
- opening league score history.

Use **All leagues** when you need the master season list or want to create,
archive, restore, or revisit a different league. Use **League home** for the
day-to-day dashboard and shortcuts for the league selected in the workspace
bar.

Double-click the league row to explore its teams and players.

## Permanent players and season pools

Open **League Manager** and **Player directory**.

The permanent player directory stores one reusable identity with a name and
optional member ID. A player can participate in any number of league seasons
and tournaments without duplicating the identity.

A player pool is a separate reusable list, normally labeled by year or season.
Pools can be copied forward and edited without changing the prior pool. Linking
a pool to a league means registrations for that league are also included in the
pool.

Use **Edit selected player** to change the central identity. Identity changes
invalidate affected verified averages so they can be checked again.

Double-click a player to see every related team and league. Use Back and
Forward inside the relationship browser to move through related records.

## Teams and rosters

Open **League Manager** and **Teams & roster**. Choose the current league or
tournament once in the shared workspace selector. Registration, Rules, Teams,
and Scores follow that selection.

The main Teams & roster page is a full-size team list. Double-click a team, or
select it and use **Manage roster**, to open that team's separate roster window.

Each registration has one of two roles:

- **Regular** — normally copied into a new weekly league score sheet.
- **Substitute** — available as a team-specific or league-wide substitute.

The roster area separates:

- regular roster;
- team substitutes;
- league substitute pool.

You can add a new player, pull an existing permanent player, move a player to a
different team, change their role, or remove the team assignment. Removing a
player from a team does not delete the league registration or permanent player.

After a team assignment changes, the registration list, player history, team
counts, league counts, and scoring selectors refresh together.

Use **View relationships** in the roster window to explore the team's leagues
and players. Use **More actions** on the team list to rename the selected team
or open its score history.

## Register one bowler

1. Open **Registration**.
2. Choose the working league or tournament.
3. Enter the bowler's name and optional member ID.
4. Choose an existing team or use **Add team** first.
5. Select **Add to this league**.

The registration is saved immediately. If signed in, the average check starts
in the background. Two registration checks may run at once, so a common name
that needs review does not block entry of the next bowler.

## Register one bowler in several leagues

1. Enter the name and optional member ID on **Registration**.
2. Select **Multiple leagues…**.
3. Use Ctrl-click to select every league or tournament the bowler is joining.
4. Highlight each selected workspace and choose **Set team for highlighted
   league**.
5. Choose an existing team, create a team by entering a new name, or leave the
   bowler unassigned.
6. Select **Register bowler**.

The application commits this as one operation. If any selected registration is
invalid or duplicated, none of the new registrations or teams are saved.

The Ctrl-click interaction is temporary; an easier checkbox-style selection is
planned.

## Register a whole team

Use **Register whole team** on Registration. Choose or enter the team name and
paste a roster in any supported text form. The same parsing rules used by roster
lookup apply here. If one entry is invalid or duplicates an existing
registration, the whole team operation is rolled back.

## Review registration lookups

The Registration counter shows the group status. A row may be Ready, missing a
member ID, looking up, or need review.

For multiple matches, open **Review / recheck**, inspect the candidate name,
member ID, association/state, membership period, and activity status, and choose
the correct person. The selected member ID is written back to the shared player
identity and appears in Player and Team management after refresh.

For very common names, use the membership ID whenever possible. The current
name-search request retrieves only the first page of ten BOWL.com candidates.

## Configure league scoring

Open **League Manager** and **Rules & setup**, then choose **Edit average &
scoring rules**. The same settings button remains available in **Scores &
history**.

Current settings are:

- games per player for each weekly sheet;
- average-rule label;
- minimum qualifying games;
- multiplier and pin adjustment;
- nearest, up, or down rounding;
- handicap base and percentage;
- blind penalty;
- vacancy score.

The current score-sheet source is the verified Standard Composite Average saved
on the registration. For example, a league can use composite × 0.9, add or
subtract pins, and choose rounding. Selecting a named prior-league average is
not available yet.

Handicap is calculated per player as:

```text
floor(max(handicap base - entering average, 0) × handicap percentage)
```

## Create and enter a weekly score sheet

1. Select the league workspace, then open **Scores & history**.
2. Select **New week** and enter the week number, optional date, and label.
3. The application copies active regular roster assignments into a permanent
   weekly snapshot.
4. Use **Add player / substitute** for a substitute, an alternate, or a
   regular row that was removed earlier. Choose which team the player bowled
   for that week.
5. Use **Add vacancy** when required.
6. Double-click a player row and enter each game's state and score.

Game states are:

- **Bowled** — requires a score from 0 through 300.
- **Blind** — counts entering average minus the league blind penalty, plus
  handicap.
- **Absent** — counts zero pins.
- **Vacancy** — uses the league vacancy score and calculated handicap.
- **Not entered** — marks the game incomplete.

Team scratch and handicap totals are calculated from player game records. They
cannot be edited independently.

## Finalize, correct, and review history

A week cannot be finalized while any game remains Not entered. A final week is
read-only until reopened.

- Initial score entry needs no reason.
- Changing a previously entered result or its entering average requires a
  reason.
- Removing a row with saved scores requires a reason.
- Reopening a final week requires a reason.

If a correction reason is missing, the score editor remains open and shows the
requirement beneath the reason field. **Cancel** always remains available and
closes the editor without saving.

Open **History & corrections** to review every week or filter to one team. Use
the **Corrections** tab in that window to see before/after values and reasons
for the selected week. Double-click a week, or use **Open score sheet**, to
return to it. Team and All leagues management also provide direct history
actions.

Weekly rows snapshot the player name, team name, role, entering average,
handicap, and game count. Later roster moves or renames do not rewrite history.

## Sign in and average lookup

1. Select **Sign in to BOWL.com**.
2. Complete sign-in on the genuine page in the private Average Assistant
   WebView2 window.
3. The helper closes after it finds the temporary session token.
4. Open **Average lookup**.
5. Use **Single lookup** or **Choose roster**, then **Look up averages**.

Passwords are entered only on BOWL.com. The application keeps the temporary
bearer token in memory and discards it on sign-out or application close.

Average lookup uses the newest record with games greater than zero where
`sport` and `challenge` are both false. The result is labeled Standard
Composite Average.

## Fix lookup issues

Open **Fixes needed** or double-click a highlighted row. Depending on the
result, you can select a candidate, correct the name, enter or replace the
membership ID, confirm an inactive member, and retry only that row. **Next
issue** moves through unresolved rows without rerunning the whole roster.

## Save or import lookup results

**Save results** supports:

- full roster;
- active/ready roster;
- inactive roster;
- needs-attention roster.

Output formats are JSON, Excel, CSV, tab-separated text, and plain text. Excel
contains a Results sheet and, when needed, a Needs Attention sheet. CSV, TSV,
text, and Excel protect text beginning with spreadsheet formula characters by
prefixing it with an apostrophe.

**Add to player list** imports every current lookup result into the permanent
player directory after confirming any unresolved entries. It reuses matching
member IDs and appropriate unclaimed blank-ID identities instead of blindly
creating duplicates.

## Backup and restore

Close Bowling Manager before copying or replacing the database.

To back up:

1. Close the application.
2. Copy `%LOCALAPPDATA%\Bowling Manager\bowling-manager.db` to another safe
   location.

To restore:

1. Close the application.
2. Keep a copy of the current database.
3. Replace `bowling-manager.db` with the known-good copy.
4. Start the application and verify leagues, teams, players, and score history.

The database is not encrypted by the application. Treat backups and exports as
personal league records.

## Troubleshooting

### The sign-in window was closed

The main Sign in button should reset. Start sign-in again when ready. Local
league work is unaffected.

### A common name does not show the right person

Enter the membership ID and retry. Name search is limited to BOWL.com's first
ten returned candidates.

### A team move does not appear

Current builds refresh all related views automatically. If the old assignment
still appears, close and reopen the app before making further edits and report
the exact screen and steps.

### A score row was removed

While the week is still Draft, select **Add player / substitute**, choose
the registered player and team, and add the row again. The original roster role
is preserved.

### The app says the database needs attention

Do not delete the database. Make a copy and retain any adjacent
`schema-v*-backup.db` files. The application leaves unsupported or unreadable
data unchanged rather than replacing it silently.
