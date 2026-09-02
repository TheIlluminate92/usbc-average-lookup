# Security and privacy policy

## Project status

Bowling Manager is an unofficial pre-alpha desktop project. It is not
affiliated with USBC or BOWL.com. The current GitHub Windows test builds are
unsigned, are not installers, and have not received an external security audit.

Use the software only for league/member records you are authorized to manage.

## Data stored locally

The application database may contain personal league information:

- bowler names;
- USBC membership IDs;
- league, tournament, team, and roster relationships;
- verified averages and games;
- weekly scores and correction reasons.

It is stored in ordinary SQLite at:

```text
%LOCALAPPDATA%\Bowling Manager\bowling-manager.db
```

The application does not encrypt the database, backups, or exports. Windows
account permissions and any device/disk encryption are the current protection
boundary. Anyone who can read the database can read its contents.

Backups such as `bowling-manager.schema-v*-backup.db`, legacy JSON files, and
exported spreadsheets contain the same class of personal data and need the same
protection.

## BOWL.com credentials and sessions

The application must never present its own username/password fields. Sign-in
opens BOWL.com's genuine page in a private application-owned WebView2 helper.
Passwords and MFA responses go directly to BOWL.com and are not exposed to the
main application.

The helper discovers the temporary bearer token created by the authenticated
page and returns it to the parent through a local in-memory stdout pipe. The
main app keeps the token only in memory. Sign-out, helper cancellation/timeout,
and application close terminate the helper and discard the app-held session.

The application must not persist:

- passwords or MFA secrets;
- bearer, access, refresh, or identity tokens;
- authorization headers;
- session cookies or browser storage;
- app-owned WebView profiles for current private-mode sign-in.

Versions 0.3 and later remove only the known legacy app-owned profile folders.
They must not inspect or remove normal Edge, Chrome, Brave, or other browser
profiles.

## Network behavior

The online lookup sends the temporary bearer token only to the observed
`apps1.bowl.com` API over HTTPS. It does not intentionally send league data,
credentials, or tokens to another service.

The BOWL.com operations are undocumented and not an official public mining API.
Acceptable use, safe rate limits, and change-notification expectations remain
unconfirmed. Do not increase concurrency, crawl the member directory, bypass
access controls, or run large live stress tests without authorization.

## Logs and diagnostics

Current normal operation does not require an application log file. Any future
diagnostic facility must redact:

- `Authorization` and cookie headers;
- token-like storage values;
- full member responses;
- unnecessary names/member IDs;
- database contents and exported rosters.

User-facing API errors should contain status/schema guidance but no request
credentials.

## Spreadsheet safety

CSV, TSV, text, and Excel exports may contain imported or remote strings.
Spreadsheet-oriented export code prefixes strings that begin with common
formula characters (`=`, `+`, `-`, `@`, tab, carriage return, or newline) so
opening a result does not execute them as formulas.

This protection applies to lookup-result exports. Future score/recap exporters
must use the same rule.

## Database safety

SQLite foreign keys, uniqueness constraints, state checks, transactions, and
application reference validation protect linked records. Schema upgrades create
an adjacent SQLite backup before modification. Legacy JSON migration builds and
checks a temporary database before moving it into place.

These safeguards reduce accidental corruption but are not access control or
encryption. Back up the database while the application is closed and test
restores periodically.

## Multi-user and cloud limitations

The current application has no user accounts, roles, permissions, shared
server, cloud sync, or supported simultaneous editing. Do not place the live
SQLite file in a synchronization folder and open it from multiple computers at
the same time.

Score correction reasons provide an operational history, not cryptographic
non-repudiation. A person with direct database access can alter local records.

## Money handling

Brackets, side pots, payouts, prize funds, and other money-handling features are
not implemented. Do not use ordinary score/change-log records as a financial
ledger.

## What must never be committed or posted

- BOWL.com passwords or MFA material
- Session cookies or browser-storage dumps
- Authorization, bearer, access, refresh, or identity tokens
- Unredacted developer-tools captures or request archives
- Real bulk member responses
- Live league databases, database backups, or exported rosters
- Screenshots containing unnecessary personal/member data

Test fixtures must be minimal and sanitized.

## Reporting a concern

Report security or privacy concerns privately to the repository owner. Do not
open a public issue containing credentials, live tokens, a league database,
member records, or steps that expose someone else's data.

Include only:

- affected version/commit;
- a concise description and impact;
- sanitized reproduction steps;
- whether local data, session material, or another person's records may have
  been exposed.

If a live token or credential is exposed, revoke/sign out first and avoid
copying the secret into the report.

## Release security checks

Before broader use, complete the security portions of
[docs/release-checklist.md](docs/release-checklist.md), especially:

- packaged helper cleanup;
- token/file inspection;
- legacy-profile boundaries;
- spreadsheet-formula protection;
- database backup/integrity/restore;
- unsigned-build disclosure;
- 200-bowler local workload and approved conservative network volume.
