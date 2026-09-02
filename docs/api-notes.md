# BOWL.com API observations

These notes document behavior observed through BOWL.com's own authenticated web
application and the current client implementation. They are not an official API
contract or permission to automate access.

Never add live cookies, authorization headers, bearer tokens, account details,
or unredacted member records to this repository, an issue, a screenshot, or a
fixture.

## Implementation status

| Operation | Client support | Used by normal workflow |
| --- | --- | --- |
| Member search by name | Yes | Yes |
| Member search by membership ID | Yes | Yes |
| Composite averages | Yes | Yes |
| League activities with pagination | Yes | No; rows are not persisted yet |
| Rerated average | No | No |

All current requests require an in-memory bearer token obtained from the user's
authenticated BOWL.com session. Signed-out behavior has not been accepted as a
supported mode.

## Base URL and authentication

The current JSON base is:

```text
https://apps1.bowl.com/Mobile/api/v1
```

Requests send:

```text
Accept: application/json
Authorization: Bearer <temporary session token>
```

The token is discovered inside the private sign-in helper and passed to the
main process through an in-memory stdout pipe. It is never persisted.

HTTP 401 and 403 are treated as an expired session. Other HTTP errors, network
failures, timeouts, invalid JSON, unsuccessful service envelopes, and unexpected
schemas are surfaced as safe API errors.

## Member search

The BOWL.com frontend uses different routes for name and ID search:

```text
Name:          GET /members/
Membership ID: GET /members/id
```

Observed query parameters:

```text
First, Last, Prefix, Suffix, ANum, Zip, Radius, State, Page, Size
```

The current client behavior is:

- membership ID present: split `prefix-suffix`, call `/members/id`, and leave
  First/Last empty;
- no membership ID: split the input name at the last word, call `/members/`,
  and leave Prefix/Suffix empty;
- set `Page=1`, `Size=10`, and `Radius=5`;
- leave association, ZIP, and state filters empty.

Sending a name to `/members/id` produced the site's generic service error rather
than the candidates shown by its member-search page.

### Known search limit

The client currently retrieves only the first page of ten name candidates. It
does not page a common name's full result set. If the correct person is not in
those ten candidates, the operator must search by membership ID. Pagination or
additional disambiguating filters are a future improvement.

### Sanitized member shape

```json
{
  "id": "<internal record id>",
  "prefix": "<member prefix>",
  "suffix": "<member suffix>",
  "first": "Example",
  "init": "Q",
  "last": "Bowler",
  "active": true,
  "assn": "Example USBC",
  "assnstate": "TX",
  "from": "<membership start>",
  "thru": "<membership end>"
}
```

A name may produce current and historical membership records. The application
keeps Multiple matches and Inactive member as explicit operator decisions. It
never assumes the first returned member is correct.

## Composite averages

The selected member's detail page requests:

```text
GET /compositeaverages
```

Parameters:

```text
size=1000&page=1&prefix=<prefix>&suffix=<suffix>
```

Sanitized envelope and record:

```json
{
  "isSuccess": true,
  "validationErrors": [],
  "errors": [],
  "data": {
    "results": [
      {
        "year": "2025",
        "sport": false,
        "challenge": false,
        "hand": "",
        "games": 188,
        "avg": 153
      }
    ]
  }
}
```

Comparison with the rendered member page showed that this record supplies the
displayed Standard Composite Average. In observed records, `year=2025` appears
under the 2024–2025 heading.

Current selection:

```text
keep sport == false
keep challenge == false
keep games > 0
choose greatest numeric year
return avg, year, and games
```

The current selection is implemented in `services/average_selector.py` and
covered by tests. It does not choose the highest individual league average.

## League activities

The member page also requests:

```text
GET /leagueactivities
```

Parameters are `size=1000`, page number, prefix, and suffix. The client follows
`totalPages` until all pages are collected and validates every pagination value
and record.

Sanitized record:

```json
{
  "lid": "<league id>",
  "lname": "Example League",
  "season": "W",
  "cid": "<center id>",
  "cname": "Example Center",
  "aid": "<association id>",
  "aname": "Example Association",
  "anum": "<association number>",
  "avg": 148,
  "games": 87,
  "year": "2025",
  "sport": false,
  "challenge": false,
  "rollngrow": false,
  "bumper": false,
  "stringpin": false,
  "pattern": "1",
  "hand": "",
  "adjavg": 0
}
```

Condition flags must come from the response and not league-name guesses. In an
observed account, leagues with names ending in `SP` had `stringpin=true` while
`sport=false`.

The rule engine can create raw and adjusted candidates from these records, but
the registration database does not yet retain them. The League scoring settings
screen therefore correctly exposes only Standard Composite as its source.

## Rerated average

The member page was observed requesting `reratedaverage` with the same member
and pagination parameters. One observed response was a successful empty
collection. The app does not call this operation, and the relationship between
rerated data and league-activity `adjavg` is not confirmed.

An empty `results` list with `totalPages=0` is a valid empty page. A missing or
non-list `results` value is a schema error.

## Response validation

The current client requires:

- a JSON object at the top level;
- `isSuccess == true` for normal operations;
- a `data` object;
- a list in `data.results`;
- typed member/average fields needed by the domain model;
- a nonnegative integer `totalPages` for paged league activities;
- dictionary records on every page.

Service messages are collected recursively from `validationErrors` and
`errors`, deduplicated, and returned without including request credentials.

## Remaining unknowns

- BOWL.com/USBC acceptable-use terms for this automation and an approved safe
  request rate.
- Rate-limit status codes, headers, and recommended backoff.
- Complete name-search pagination behavior and practical disambiguating
  filters.
- Exact expired-session and account-policy behavior across all endpoints.
- Meanings of all `season`, `pattern`, and `hand` codes.
- Rerated-average response shape and relationship to `adjavg`.
- Whether prefix/suffix may be retained long term beyond the ordinary member ID.
- Stability and change-notification expectations for these undocumented
  operations.

## Safe discovery process

1. Use an account and member record you are authorized to inspect.
2. Capture only URL, method, parameter names, status, and response shape needed
   for the question.
3. Remove authorization, cookies, tokens, account identifiers, and unrelated
   personal data before saving notes or fixtures.
4. Do not bypass authentication, access controls, throttling, or site behavior.
5. Record failures and schema changes; do not make the parser silently accept
   guessed data.
6. Add only sanitized, minimal fixtures under `tests/fixtures/` after review.
