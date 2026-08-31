# Architecture

The application is intentionally split so BOWL.com-specific details do not leak
through the GUI or export logic.

```text
Tkinter Windows GUI
        |
        +-- browser authentication boundary (only if required)
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

The app launches the selected Microsoft Edge, Google Chrome, or Brave
installation through Playwright with a separate application-owned profile for
each browser. It first checks a remembered session without showing a browser,
avoiding a visible open-and-close flash when no interactive login is needed.
The user signs in on BOWL.com's genuine page.
The app observes the bearer session that page sends to the verified BOWL.com API
and retains it only in memory for lookups. It does not inspect or store the
password and never writes the bearer token to logs, exports, or source control.
The user can remove the selected app-owned profile with **Forget login** without
altering their everyday browser profile.
