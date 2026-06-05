# Security Policy

## Supported Versions

Security fixes target the current `main` branch.

## Reporting a Vulnerability

Please do not open a public issue for secrets exposure, auth bypasses, unsafe
scraping behavior, or data-leak bugs. Report privately to the repository owner
or use GitHub private vulnerability reporting if it is enabled.

Include:

- Affected component
- Reproduction steps
- Impact
- Whether any credentials, resumes, or job-search data may be exposed

## Sensitive Data

SignalRank handles resume text, profile preferences, application history, and
API keys. Keep these out of Git:

- `.env` and `.env.local`
- API keys and session cookies
- Resume PDFs, private profile JSON/YAML, and generated cover letters
- Database dumps and benchmark snapshots
- Local worker output and temporary files

If a real secret was ever committed, rotate it and rewrite Git history before
making the repository public.
