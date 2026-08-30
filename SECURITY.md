# Security policy

## Sensitive data

Never commit or post:

- BOWL.com passwords
- Session cookies or browser storage
- Authorization, access, refresh, or identity tokens
- Unredacted request captures
- Bulk member data or exported league rosters

The application must not present username/password fields. If authentication is
required, credentials go directly to the genuine BOWL.com login flow and are
never exposed to application code.

## Reporting

Keep this repository private during discovery. Report security concerns to the
repository owner without including live credentials or unnecessary personal
data in an issue.

