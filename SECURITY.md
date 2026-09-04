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

This repository and its issues are public. Report security concerns privately
to the repository owner; do not disclose live credentials, personal data, or
exploitable vulnerability details in a public issue. If a private contact
channel has not been established, ask the owner for one without posting the
sensitive details.
