# BOWL.com API discovery notes

These notes capture observed behavior from browser developer tools. They are not
an official API contract. Do not include cookies, authorization headers, tokens,
or private member data in this repository.

## Observed member-search response

The authenticated frontend uses separate `GET` routes for the two searches:

```text
Name:          https://apps1.bowl.com/Mobile/api/v1/members/
Membership ID: https://apps1.bowl.com/Mobile/api/v1/members/id
```

Observed query parameters:

```text
First, Last, Prefix, Suffix, ANum, Zip, Radius, State, Page, Size
```

A name search fills `First` and `Last` on `members/`. An ID search fills
`Prefix` and `Suffix` on `members/id`. Both use `Page=1`, `Size=10`, and leave
unused search fields empty. Sending a name to `members/id` produces a generic
service error instead of candidates. Requests use an in-memory bearer token
supplied by the signed-in BOWL.com session. Tokens must never be copied into
code, configuration, fixtures, documentation, logs, or screenshots.

The Find a Member frontend returns JSON records containing fields similar to:

```json
{
  "id": "<internal member record id>",
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

A single name can produce current and historical membership records. The UI
must therefore support `Multiple matches` and `Inactive member` instead of
assuming the first result is correct.

## Observed composite-average response

The member detail page sends an authenticated `GET` request to:

```text
https://apps1.bowl.com/Mobile/api/v1/compositeaverages
```

Observed query parameters are `size=1000`, `page=1`, and the selected member's
`prefix` and `suffix`. A sanitized response shape is:

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

Comparison against the rendered site showed that this record supplies the
Standard Composite Average. The observed `year` value `2025` corresponded to a
site label of 2024–2025.

## Current selection rule

```text
filter sport == false
filter challenge == false
filter games > 0
choose greatest numeric year
return avg
```

This rule is implemented in `services/average_selector.py` and covered by unit
tests. It remains subject to the league operator confirming that Standard
Composite Average is the desired number.

## Experimental complete-average review

The member detail page was also observed calling:

```text
https://apps1.bowl.com/Mobile/api/v1/leagueactivities
https://apps1.bowl.com/Mobile/api/v1/reratedaverage
```

Both calls appeared to use `size`, `page`, `prefix`, and `suffix`, like the
composite request. The rendered page confirms that league information can
include league name, average, games, condition, converted average, season, and
center/association. The rerate list can include adjusted and entering averages,
tournament, date, and assigning official.

The exact raw JSON field names for these two responses have not yet been saved
as sanitized fixtures. Version 0.4 therefore accepts common case and naming
variations, retains every parsed record, and raises a visible schema error if a
nonempty record cannot be understood. It must never silently substitute or
drop an unknown record. A live authorized test and sanitized fixtures are
required before merging the experimental branch into `main`.

## Unknowns to resolve

- Whether either endpoint works in a signed-out browser session.
- Session mechanism and whether an embedded browser can safely share it with an
  HTTP client.
- Response codes/shapes for expired sessions, validation failures, server
  errors, and rate limiting.
- Acceptable automation under BOWL.com/USBC terms and a safe request rate.
- Whether prefix/suffix should ever be retained outside the current lookup.

## Safe discovery checklist

1. Use an account and member record you are authorized to inspect.
2. Capture URL, method, query/body, status code, and response JSON.
3. Remove `Cookie`, `Authorization`, bearer tokens, account identifiers, and
   unrelated personal data before creating a fixture.
4. Repeat the request while completely signed out.
5. Record error responses without trying to bypass authentication or access
   controls.
6. Add sanitized fixtures under `tests/fixtures/` only after review.
