# Architecture

The application is intentionally split so BOWL.com-specific details do not leak
through the GUI or export logic.

## Registration domain

Registration is intentionally separated into six records:

- `BowlerProfile` is the reusable person identity and optional USBC member ID.
- `PlayerPool` is an independently editable season/year list.
- `PlayerPoolEntry` connects a reusable bowler identity to a season pool.
- `Competition` is one league season or one tournament.
- `Team` belongs to exactly one competition.
- `Registration` connects a bowler to a competition and its current team while
  retaining regular/substitute role, lookup state, selected average, and
  withdrawal state.

This prevents annual team changes or player-pool edits from rewriting earlier
seasons. A competition can link to a player pool; current and future
registrations are then included in that pool. Removing a registration from a
team clears only the team assignment, while withdrawal remains a separate
operation. The storage adapter is a local, schema-versioned SQLite database.
Writes run in transactions and the schema enforces primary keys, foreign keys,
unique registrations, and the allowed competition, roster, and verification
states. The UI talks to `RegistrationStore`, not directly to SQL, so a later
shared PostgreSQL service does not need to change the registration screens.

On the first SQLite launch, the store can import schema-version 1 or 2 of the
former JSON document. Migration is built in a temporary database, checked with
SQLite's integrity checker, and moved into place only after success. The source
JSON remains untouched and receives a separate pre-SQLite backup copy.

BOWL.com checks are optional. Manual entry works while signed out, and a
two-worker background queue prevents a slow or ambiguous lookup from blocking
the registration desk or creating an unbounded burst of requests. Ambiguous
candidate lists remain a deliberate operator decision.

The desktop workspace presents four domain-focused tabs. Registration is the
fast operational screen. Player management edits the central identity and
invalidates averages that may no longer belong to that identity. Team
management always requires a selected league season or tournament and never
mixes teams across competitions. It separates regulars, team-specific
substitutes, and unassigned league-wide substitutes. League and tournament
management owns names, season labels, type, player-pool links, and reversible
archival.

```text
Tkinter Windows GUI
        |
        +-- private WebView2 authentication boundary (only if required)
        |
        +-- lookup coordinator
                |
                +-- member-search client
                +-- explicit match resolution
                +-- composite-average client
                +-- standard-average selector
                +-- result/status mapping
        |
        +-- clean results CSV / issues CSV / clipboard
```

## Design decisions

- **Desktop first:** version 1 is for one Windows user, so Docker and a shared
  server add administration without improving the workflow.
- **Python foundation:** the app can remain small and later be packaged as a
  portable executable. A move to .NET remains possible if WebView2 session
  integration proves substantially safer or simpler.
- **No guessed endpoints:** the current client is an unconfigured boundary until
  sanitized request details are captured.
- **No silent matching:** ambiguity is a normal domain outcome, not an exception.
- **Separate exports:** a clean import file must not hide missing or failed rows.
- **Pure selection logic:** choosing the composite average is independent of the
  network and GUI, making the business rule easy to test.
- **Appliance-like UI:** technical complexity stays behind a four-step flow:
  enter names, look up, resolve any highlighted name, save results.

## Proposed integration flow

```text
input name
  -> member search
  -> zero matches: Not found
  -> multiple plausible matches: Multiple matches
  -> inactive-only match: Inactive member
  -> selected active member (prefix + suffix)
  -> composite averages
  -> no qualifying record: No average
  -> newest standard record: Found
```

Authentication failures map to `Login expired`; transport, server, schema, and
rate-limit failures map to `API error` with a safe user-facing note.

## Authentication model

The app opens BOWL.com's genuine page inside an application-owned WebView2
window. That window runs in a dedicated packaged helper process and uses private mode, so it does
not share data with or open tabs in Microsoft Edge, Google Chrome, or Brave.
The app reads the bearer session established by BOWL.com and sends only that
temporary token through an in-memory pipe to the main window. It does not
inspect or store the password and never writes the bearer token to logs,
exports, configuration, or source control. The WebView process is ended after
sign-in, on sign-out, and when the application closes, discarding its cookies
and browser storage.
