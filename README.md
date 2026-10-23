# US market monitor

Public GitHub Actions workflow for a US market and portfolio monitor.

- Runs in GitHub Actions, independent of the local computer.
- Sends a daily HTML email at 19:00 SGT on US trading days.
- Sends alerts at the configured intraday slots when a level or rule is triggered.
- Uses Yahoo Finance public data, which may be delayed around 15 minutes.

## Setup

Add these repository secrets in Settings > Secrets and variables > Actions:

- EMAIL_PROVIDER = resend
- EMAIL_FROM = onboarding@resend.dev
- EMAIL_TO = your receiving email
- RESEND_API_KEY = your Resend API key
- PORTFOLIO_JSON = optional personal holdings/watchlist JSON

Set the repository variable DRY_RUN to false to send real email.

## Schedule (Asia/Singapore)

- 00:00, 04:00, 08:00, 12:00, 16:00: four-hour checks.
- 19:00, 20:00, 21:00: evening hourly checks; 19:00 is the full daily report.
- 21:00, 21:15, 21:30: the 15-minute pre-open window.
- 21:30 through 04:30 at :30: hourly intraday checks.

GitHub Actions cron uses UTC; the workflow contains the converted cron lines. GitHub scheduled workflows can be delayed by several minutes.

## Data and privacy

The code contains no account numbers, positions, or email credentials. Holdings are read from the PORTFOLIO_JSON secret at runtime. The email contains conditional monitoring rules, not investment advice, and never places orders.
