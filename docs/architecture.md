# Architecture

The application is intentionally split so BOWL.com-specific details do not leak
through the GUI or export logic.

## Registration domain

Registration is intentionally separated into four records:

- `BowlerProfile` is the reusable person identity and optional USBC member ID.
- `Competition` is one league season or one tournament.
- `Team` belongs to exactly one competition.
- `Registration` connects a bowler to a competition and its current team while
  retaining lookup state, selected average, and withdrawal state.

This prevents annual team changes from rewriting earlier seasons. The first
storage adapter is a local, schema-versioned JSON document written atomically.
The UI talks to `RegistrationStore`, not directly to JSON, so a later SQLite or
shared-service adapter does not need to change the registration screens.

BOWL.com checks are optional. Manual entry works while signed out, and a
two-worker background queue prevents a slow or ambiguous lookup from blocking
the registration desk or creating an unbounded burst of requests. Ambiguous
candidate lists remain a deliberate operator decision.

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
