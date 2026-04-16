# name.com Source

## Overview

The `name` source downloads the complete expiring-domains list from
[name.com](https://www.name.com/account/download/expired).  It uses
cookie-based authentication — no API key is required.  If the session
cookies are missing or expired, DDig automatically re-authenticates via
Playwright headless Chromium.

## Authentication

name.com uses session cookies, not a persistent API token.

**Fast path (no browser required):**
If `NAME_SESSION` is set and the cookie is still valid, DDig issues a
single `requests.get` download — no Playwright needed.

**Slow path (Playwright re-auth):**
When the download endpoint redirects to the login page, DDig launches a
headless Chromium browser, fills in your credentials, captures the new
session cookies, writes them back to `.env`, and retries the download.

**MFA:**
If name.com prompts for a one-time code after login, DDig will pause and
print `name.com MFA code:` in the terminal.  Enter the 6-digit code and
press Enter to continue.  After a successful MFA login the new session
cookie is saved to `.env`, so subsequent fetches will not require MFA
until the session expires again.

## Refreshing Cookies Manually

If automated re-auth fails, copy fresh cookies from your browser:

1. Open **DevTools** → **Application** → **Cookies** → `www.name.com`
2. Copy the value of `PREG_IDT` into `NAME_SESSION`
3. Copy the value of `acct_login_time` into `NAME_LOGIN_TIME`

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `NAME_USER` | name.com username / email | ✅ |
| `NAME_PASS` | name.com password | ✅ |
| `NAME_SESSION_NAME` | Session cookie name (default: `PREG_IDT`) | ✅ |
| `NAME_SESSION` | Session cookie value | ✅ |
| `NAME_LOGIN_TIME_NAME` | Login-time cookie name (default: `acct_login_time`) | ✅ |
| `NAME_LOGIN_TIME` | Login-time cookie value | ✅ |

Add these to your `.env` (copy from `.env.example`):

```bash
NAME_USER=you@example.com
NAME_PASS=yourpassword
NAME_SESSION_NAME=PREG_IDT
NAME_SESSION=<value from DevTools>
NAME_LOGIN_TIME_NAME=acct_login_time
NAME_LOGIN_TIME=<value from DevTools>
```

## CSV Format

The download endpoint returns a **tab-separated** file (despite the `.csv`
extension) with the following columns:

| Column | Description | Maps to `Domain` field |
|---|---|---|
| `domain_name` | Fully-qualified domain name | `fqdn`, `name` |
| `created_date` | Original registration date | _(ignored)_ |
| `expiring_date` | Expiry / drop date (ISO 8601 with `+00:00`) | `drop_date` |
| `price` | Renewal price in USD | _(ignored)_ |
| `tld` | Top-level domain | `tld` |
| `traffic_data` | Estimated monthly visits | _(ignored)_ |

## Caching

Downloaded files are written to `data/name_YYYY-MM-DD.tsv`.  If today's
file already exists, DDig skips the network request and parses the cached
copy.  The `data/` directory is `.gitignore`d.

## Usage

```bash
# Fetch with defaults
ddig fetch --source name

# Fetch, then run NLP scoring immediately
ddig fetch --source name --score

# Show debug output
ddig fetch --source name --verbose
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `requests.exceptions.HTTPError: 302` | Session expired — run `ddig fetch --source name` to trigger Playwright re-auth, or paste fresh cookies into `.env` manually |
| Playwright hangs at MFA screen | Enter the MFA code in the terminal when prompted |
| `NAME_SESSION` not set | Add all `NAME_*` vars to `.env` (see table above) |
| Downloaded file is an HTML login page | Cookie is invalid — delete `data/name_*.tsv` and re-fetch to force re-auth |