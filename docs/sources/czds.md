# ICANN CZDS Source

The ICANN Centralized Zone Data Service (CZDS) provides **official zone files**
for gTLDs — the most complete dataset available, containing every registered
domain for a TLD.

## What Is a Zone File?

A zone file lists every domain registered under a TLD. For example, the `.app`
zone file contains every currently registered `.app` domain — millions of them.
Zone files are updated **daily**.

> **Note:** `.com` and `.net` are **not available** — Verisign controls those.
> Most new gTLDs are available: `.app`, `.dev`, `.io`, `.shop`, `.online`, etc.

## Registration

1. Create a free account at **https://czds.icann.org**
2. Request access to individual TLDs at **https://czds.icann.org/zone-requests/new**
3. Approval typically takes **24–48 hours** per TLD
4. Some TLDs auto-approve instantly

### Recommended TLDs to Request

```
app  dev  io  shop  online  store  club  co  tech  site
info  biz  us  me  tv  cc  org
```

## Credentials

| Env var      | Description                                       |
|--------------|---------------------------------------------------|
| `CZDS_USER`  | Your ICANN account email                          |
| `CZDS_PASS`  | Your ICANN account password                       |
| `CZDS_TOKEN` | JWT bearer token — managed automatically by ddig  |

```bash
# .env
CZDS_USER=your@email.com
CZDS_PASS=yourpassword
CZDS_TOKEN=eyJhbGci...   # populated automatically by ddig czds-auth
```

> ⚠️ Always use `.env` — never `export CZDS_TOKEN=` in the shell.
> ⚠️ `.env` is gitignored — never commit it.

## Authentication

ICANN uses **Okta OAuth2** for authentication. `ddig` handles this automatically
using Playwright — a real browser session is used to log in, capture the JWT
from a network request, and save it to `.env`.

### `ddig czds-auth` — Automatic Token Refresh

This is the primary authentication method. Run it whenever the token expires:

```bash
ddig czds-auth           # opens browser, logs in, saves token to .env
ddig czds-auth --verbose # show detailed steps
```

The flow:
1. Opens a Playwright (Chromium) browser window
2. Navigates to `https://czds.icann.org`
3. Clicks **Sign In**, fills `#emailAddress`, submits
4. Fills `input[type="password"]`, submits
5. Waits for MFA if prompted (up to 2 min — complete manually in the browser)
6. Intercepts the JWT from the first `czds-api.icann.org` network request
7. Saves the token to `.env` automatically

> The JWT expires in **~1 hour**. If `ddig fetch --source czds` returns 401,
> the token is refreshed automatically via Playwright — no manual steps needed.

### Manual Token (Fallback)

If Playwright auth fails for any reason:

1. Log in at **https://czds.icann.org**
2. Open DevTools → **Network** tab
3. Filter by `czds-api.icann.org`
4. Click any matching request → **Headers** → `Authorization: Bearer eyJ…`
5. **Right-click the value → Copy value** (do not click-drag — it truncates)
6. Paste into `.env`:

```bash
CZDS_TOKEN=eyJhbGci...   # 1193 chars, no quotes
```

> Copy from a request to `czds-api.icann.org` specifically — not
> `account.icann.org` or `czds.icann.org` (the frontend).

## Usage

```bash
# Re-authenticate (run when token expires)
ddig czds-auth

# List your approved TLDs (834 available)
ddig czds-tlds

# Fetch a single TLD (~1.2M domains, ~2 min)
ddig fetch --source czds --tlds app

# Fetch multiple TLDs
ddig fetch --source czds --tlds app,dev,io,shop

# Fetch all approved TLDs
ddig fetch --source czds

# Fetch and score immediately
ddig fetch --source czds --tlds app,dev --score --verbose

# Limit number of TLDs processed (useful for testing)
ddig fetch --source czds --max-tlds 3 --verbose
```

## Zone File Caching

Zone files are cached daily at `~/.ddig/czds_cache/` to avoid re-downloading:

```
~/.ddig/czds_cache/
  app_2026-04-13.zone.gz
  dev_2026-04-13.zone.gz
  io_2026-04-13.zone.gz
```

Files are re-downloaded automatically the next day.

```bash
# Force re-download by removing cached files
rm ~/.ddig/czds_cache/*.zone.gz
```

## Data Fields Provided

| Field        | Description                              |
|--------------|------------------------------------------|
| `fqdn`       | Fully qualified domain name              |
| `name`       | Domain name without TLD                  |
| `tld`        | Top-level domain                         |
| `source`     | `czds`                                   |
| `fetched_at` | Timestamp of fetch                       |

> Zone files contain **all registered** domains, not just expired/dropping ones.
> Use `ddig score` + `ddig search --no-numbers --no-hyphens --min-score 0.7`
> to filter for interesting names.

## API Reference

| Endpoint                              | Description                        |
|---------------------------------------|------------------------------------|
| `GET /czds/downloads/links`           | List approved zone file URLs       |
| `GET /czds/downloads/{tld}.zone`      | Download a zone file (gzipped)     |

## Performance

| TLD    | Domains     | Download + Parse |
|--------|-------------|-----------------|
| `.app` | ~1,187,874  | ~2 min           |
| `.dev` | ~500K est.  | ~1 min           |
| `.io`  | ~500MB compressed — allow 5+ min |

## Notes

- Zone files can be **very large** — allocate time accordingly
- Parsing is streamed — memory usage stays flat regardless of file size
- Only `NS` and `SOA` records are parsed; other record types are skipped
- Domains are deduplicated within each zone file
- JWT expires **~1 hour** after issue — `ddig fetch` auto-refreshes if expired
- 834 TLDs currently approved for this account

## Role in DDig

CZDS is kept as a source but **used selectively and intentionally**. Here's why:

### What CZDS Is
CZDS provides the **complete zone file** for a TLD — every registered domain under `.app`, `.io`, `.dev` etc. It is **not** a list of dropping or expiring domains.

### Why It's Not the Primary Source
- Zone files contain all registered domains — the vast majority will never drop
- Fetching `.app` gives 1.2M domains, of which maybe 500/day actually drop
- DropCatch already provides the dropping list with drop dates — CZDS adds no expiry signal
- Running CZDS without filtering creates millions of dead-weight records (no drop_date, no expiry_date)

### When It IS Useful
CZDS is useful only if you want to **pre-score a specific TLD** before domains appear in DropCatch — so composite scores are ready instantly when a domain surfaces. This is a deliberate choice, not a default workflow.

### Decision
> **CZDS remains as a source but should only be run intentionally for specific TLDs you are monitoring.**
> Do not run `ddig fetch --source czds` as part of a regular daily workflow.
> Prefer `ddig fetch --source dropcatch` for day-to-day use.

The 1,332 `.app` CZDS records in the DB are legitimate — they overlap with DropCatch dropping domains and provide pre-scored NLP data for that TLD.