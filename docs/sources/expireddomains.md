# ExpiredDomains Source

ExpiredDomains.net aggregates expired, deleted, and expiring domains with
rich SEO metrics: backlinks, Majestic Trust Flow / Citation Flow, domain age,
and Alexa rank — the richest signals available for domain valuation.

## Requirements

This source uses **Playwright** (headless Chromium) because the results table
is rendered by JavaScript — a plain HTTP scraper sees an empty table.

```bash
pip install playwright
playwright install chromium
```

## Registration

Free account required: **https://www.expireddomains.net/register/**

- Free accounts: ~200 results per list, limited TLD filtering
- Paid accounts: unlimited results, full TLD filtering, more lists

## Credentials

Two cookies are required. Get them from your browser after logging in:

1. Log in at **https://www.expireddomains.net/login/**
2. Open DevTools → **Application** → **Cookies** → `expireddomains.net`
3. Copy both cookie values into `.env`

| Env var                            | Cookie name            | Lifetime     | Description               |
|------------------------------------|------------------------|--------------|---------------------------|
| `EXPIREDDOMAINS_SESSION_NAME`      | `ExpiredDomainssessid` | Short-lived  | Cookie name (don't change)|
| `EXPIREDDOMAINS_SESSION`           | `ExpiredDomainssessid` | Short-lived  | Session cookie value      |
| `EXPIREDDOMAINS_REMEMBER_COOKIE_NAME` | `reme`              | Long-lived   | Cookie name (don't change)|
| `EXPIREDDOMAINS_REMEMBER_SESSION`  | `reme`                 | Long-lived   | Remember-me cookie value  |
| `EXPIREDDOMAINS_USER`              | —                      | —            | Username (password login) |
| `EXPIREDDOMAINS_PASS`              | —                      | —            | Password (password login) |

```bash
# .env
EXPIREDDOMAINS_SESSION_NAME=ExpiredDomainssessid
EXPIREDDOMAINS_SESSION=<paste sessid value here>
EXPIREDDOMAINS_REMEMBER_COOKIE_NAME=reme
EXPIREDDOMAINS_REMEMBER_SESSION=<paste reme value here>
```

> The `reme` cookie is long-lived — refresh it when `ddig doctor` shows it
> as expired or when the scraper logs you out immediately.

### Why Two Cookies?

The site uses:
- `ExpiredDomainssessid` — standard Django session cookie, short-lived
- `reme` — persistent remember-me token, survives browser restarts

Both must be present for `member.expireddomains.net` to accept the session.

## Available Lists

| List name    | URL path                        | Description                        |
|--------------|---------------------------------|------------------------------------|
| `deleted`    | `/domains/combinedexpired/`     | Recently deleted/dropped (default) |
| `expired`    | `/domains/expireddomains/`      | Recently expired, not yet deleted  |
| `expiring`   | `/domains/expiringdomains/`     | Expiring soon — still registered   |
| `registered` | `/domains/newlyregistered/`     | Recently registered (monitoring)   |

> ⚠️ Results are served from **member.expireddomains.net** — not www.
> The scraper navigates there automatically after injecting cookies.

## Usage

```bash
# Default (deleted domains, 10 pages, headless)
ddig fetch --source expireddomains

# Specific list
ddig fetch --source expireddomains --feed expired

# Filter by TLD (paid accounts only)
ddig fetch --source expireddomains --feed deleted --tld com

# Control pages scraped (25 results/page)
ddig fetch --source expireddomains --feed deleted --pages 5

# Show browser window — useful for debugging login/bot issues
ddig fetch --source expireddomains --no-headless --verbose

# Full pipeline with NLP scoring
ddig fetch --source expireddomains --feed deleted --pages 10 --score --verbose
```

## Data Fields Provided

| Field        | Description                                   |
|--------------|-----------------------------------------------|
| `fqdn`       | Fully qualified domain name                   |
| `name`       | Domain name without TLD                       |
| `tld`        | Top-level domain                              |
| `backlinks`  | Number of backlinks                           |
| `drop_date`  | Date the domain became/becomes available      |
| `source`     | `expireddomains`                              |
| `fetched_at` | Timestamp of fetch                            |

## Diagnostics

### `ddig doctor`
Checks all credentials and shows whether both cookies are set and non-empty.
Run this first when something breaks.

```bash
ddig doctor
```

### `ddig ed-debug`
Opens a visible Playwright browser, navigates to the login page, and prints
a table of every input field's `name`, `id`, `type`, `placeholder`, and
recommended selector. Run this when login stops working after a site update.

```bash
ddig ed-debug
```

Example output:
```
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ type     ┃ name          ┃ id            ┃ placeholder        ┃ selector                   ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ text     │ login         │ inputLogin    │ Username           │ #inputLogin                │
│ password │ password      │ inputPassword │ Password           │ #inputPassword             │
└──────────┴───────────────┴───────────────┴────────────────────┴────────────────────────────┘
```

If the `id` values change, update `_login()` in `expireddomains.py` to use
the new selectors.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Playwright is required` | Not installed | `pip install playwright && playwright install chromium` |
| `Cookie rejected` error | Both cookies expired | Re-copy both cookies from DevTools, update `.env` |
| Logged out immediately | Stale session cookie | Refresh `EXPIREDDOMAINS_SESSION` from DevTools |
| Login wall mid-scrape | Session expired during run | Refresh both cookies, `reme` is more stable |
| Empty results table | JS didn't render | Add `--no-headless` to observe what's happening |
| Login form not filled | Selectors changed | Run `ddig ed-debug` to find new selectors |
| Bot detection / redirect | Playwright fingerprint detected | Already mitigated; try `--no-headless` to confirm |

## Notes

- Each page contains **25 results** — `--pages 10` = 250 domains max (free)
- Paid accounts lift the result cap significantly
- TLD filtering (`--tld`) requires a paid account
- ~2s delay between pages is enforced to avoid rate limiting
- `--no-headless` opens a visible browser — always use it when debugging
- Cookies are injected on `www.expireddomains.net` first, then the browser
  navigates to `member.expireddomains.net` — this order is required