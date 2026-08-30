# Product requirements

## Goal

Give a league operator a small Windows application that converts a roster of
bowler names into reliable `Name,Average` output without requiring manual
BOWL.com lookups or exposing account credentials to the application.

## Version 1 scope

### Input

- Choose a CSV or delimited text file containing a name and optional membership
  ID. Supported delimiters are comma, tab, pipe, and semicolon.
- Also accept simple lines in the form `Name (7824-376245)`.
- Trim blank lines while retaining the original display name.
- Show duplicate input names rather than silently discarding them.

### Authentication

- First test whether the required JSON endpoints work anonymously.
- If sign-in is required, open the genuine BOWL.com login flow in a browser or
  embedded browser control.
- Never collect, log, transmit elsewhere, or store a BOWL.com password.
- Support the site's normal MFA and password-manager behavior.
- Distinguish signed out, signed in, and expired-session states.
- Sign-out must clear application-held session material.

### Lookup and matching

- Search by bowler name through the observed JSON member-search operation.
- Do not silently choose among multiple plausible members.
- Surface enough non-sensitive match context to choose the correct person,
  including active state, association, state, and membership period when
  available.
- Use the selected member's `prefix` and `suffix` for the composite-average
  request.
- Prefer an active record only when it is uniquely resolvable; otherwise ask the
  user.

### Average selection

- Choose the newest record where `sport == false`, `challenge == false`, and
  `games > 0`.
- Treat the returned value as the Standard Composite Average.
- Preserve year and games as explanatory metadata.
- The observed `year` maps to the ending year shown by BOWL.com (for example,
  `2025` corresponds to the displayed 2024–2025 season). Verify this with more
  records before relying on it in user-facing labels.
- The business owner must still confirm that Standard Composite Average—not the
  highest individual league average—is the desired league input rule.

### Required outcomes

Every input row must end in one of these states:

| Status | Meaning | Next action |
| --- | --- | --- |
| Found | One member and a qualifying average were resolved | Exportable |
| Not found | Search returned no plausible member | Correct name or handle manually |
| Multiple matches | More than one plausible member remains | User selects a member |
| No average | Member exists but has no qualifying composite | Handle manually |
| Inactive member | Only an inactive record was found | Confirm or search again |
| Login expired | Authentication is no longer valid | Sign in, then retry |
| API error | Network, server, schema, or rate-limit failure | Retry failed rows |

### Output

- Results table columns: Bowler, Average, Status, Notes.
- Summary counts for processed rows and each result status.
- One JSON document containing every bowler, optional membership ID, average,
  status, and plain-language notes.
- Retry temporary failures automatically without asking the user to understand
  request or API errors.

### User experience

- The normal workflow is only: open, enter names, look up, save.
- Do not expose endpoint settings, authentication tokens, request details,
  technical logs, or configuration fields.
- If sign-in is required, present one plain **Sign in to BOWL.com** action and
  return directly to the lookup after it succeeds.
- Use one **Save Results** action that writes the complete JSON document.
- Describe failures as an action the user can take, such as “Sign in again” or
  “Check this spelling,” while retaining technical detail only in redacted logs.

## Quality and safety requirements

- Keep credentials, cookies, tokens, and member response data out of logs and
  source control.
- Redact sensitive headers from diagnostics.
- Use conservative request concurrency and documented backoff.
- Detect unexpected response schemas instead of silently producing bad data.
- Avoid recording full member histories unless the user explicitly exports a
  result.
- Package for Windows as a portable executable after integration is verified.

## Acceptance criteria for enabling live lookups

- Sanitized endpoint details and response fixtures are documented.
- Anonymous-versus-authenticated behavior is confirmed.
- Terms/permission and an acceptable request rate are reviewed.
- Member matching and average selection have fixture-based tests.
- All required status paths have tests.
- A 40–150-name test roster completes without skipped or duplicated rows.
- Exports open correctly in Excel and preserve every input outcome.

## Out of scope for version 1

- Docker or a shared web service.
- Storing BOWL.com usernames or passwords.
- Automatically choosing an ambiguous person.
- Calculating a composite from individual league rows when BOWL.com already
  provides the Standard Composite Average.
- Publishing the repository or distributing an executable before the live
  integration and usage terms are reviewed.
