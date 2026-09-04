# Product requirements

> Historical 0.3 requirements. Current behavior and supported exports are
> documented in the [README](../README.md) and [Database design](database-design.md).

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

## Version 2 working scope

This milestone turns the verified working model into an appliance-like tool for
nontechnical league operators. The items below are accepted requirements unless
called out as an open decision.

### Simplified sign-in

- Open the genuine BOWL.com sign-in inside one private Average Assistant
  window, without opening tabs in Microsoft Edge, Google Chrome, or Brave.
- Detect the authenticated session without requiring the user to manually
  search for a member.
- Keep one stable sign-in window open until authentication finishes and avoid
  rapid extra-window opening or closing.
- If direct session detection is not reliable, perform a harmless automatic
  verification request and return the user directly to the app.
- Continue to keep passwords out of the app and authentication material out of
  saved files and logs.
- Discard the private window's cookies and storage after sign-in, on sign-out,
  and when the application closes; retain only the temporary token in memory.

### Import formats

- Accept CSV (`.csv`), tab-separated (`.tsv`), delimited text (`.txt`), JSON
  (`.json`), and modern Excel (`.xlsx`).
- Automatically recognize common headings such as `Name`, `Bowler`, `Member
  ID`, `USBC ID`, and `Membership Number`.
- Accept combined names or separate first-name and last-name columns.
- Preserve membership IDs as text, including hyphens and leading zeroes.
- Ignore empty rows and report rows that cannot be understood.
- Use the first meaningful Excel sheet automatically; ask the user only when
  multiple meaningful sheets require a choice.
- Defer legacy Excel (`.xls`) unless real input files demonstrate a need.

### Main navigation and result views

- Use a clean, Arr-inspired Windows interface with a restrained navy,
  wood/amber, and status-color palette.
- Present the workflow as Sign in, Choose roster, Review, and Save.
- Provide tabs for at least:
  - **All results** — every imported bowler and current outcome.
  - **Fixes needed** — only unresolved or failed rows requiring attention.
- Show the number of affected rows in the **Fixes needed** tab.
- Provide **Clear results**. It clears the current in-app results without
  changing or deleting the original roster file.

### In-app corrections

- Preserve candidate member records for ambiguous searches instead of reducing
  them to a status message.
- Let the user resolve **Multiple matches** inside the app by selecting a member
  using name, membership ID, association/state, membership period when
  available, and active/inactive status.
- After selection, retrieve the selected member's average and update only that
  result row.
- Let the user correct a name or enter/replace a membership ID for **Not found**
  and incorrect-ID outcomes, then retry only that row.
- Allow confirmation of an inactive member when appropriate.
- Provide **Next issue** so several problem rows can be resolved in sequence.
- Do not require the entire roster lookup to be rerun after a correction.
- Permit saving with unresolved rows, but show a clear count and confirmation
  before doing so.

### Output formats and roster subsets

- Provide one **Save results** workflow with JSON, CSV, TSV/text, and Excel
  (`.xlsx`) choices.
- Keep exports understandable with common fields: name, membership ID, average,
  year, games, status, and notes.
- JSON may include additional structured details needed by another program.
- Excel should include a complete-results sheet and a needs-attention sheet when
  applicable.
- Let the user save useful subsets without rerunning the lookup:
  - **Full roster** — every imported bowler and every status.
  - **Active/ready roster** — successfully resolved active bowlers.
  - **Inactive roster** — confirmed or detected inactive members.
  - **Needs-attention roster** — unresolved matches, not found, no average,
    login failures, and API errors.
- Default to **Full roster** so no bowler is silently omitted.
- Show the number of records that will be written before saving.

### Version 2 acceptance checks

- All supported input types produce the same normalized internal roster.
- Membership IDs survive every import/export round trip unchanged.
- Multiple ambiguous rows can be fixed consecutively inside the app.
- Correcting one row does not discard or rerun completed rows.
- Tab counts and save-subset counts remain accurate after every correction.
- Every output format preserves all selected rows and their statuses.
- Clearing results leaves the source roster file untouched.
