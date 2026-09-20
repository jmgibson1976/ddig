# NRD (Newly Registered Domains) Source

Fetches lists of newly registered domain names from two free feeds.
Used by `ddig purge-registered` to identify and remove domains from the
DDig database that have since been registered by someone else.

## Authentication

None required for either feed.

## Feeds

| Feed | URL | Lookback | Volume |
|------|-----|----------|--------|
| cenk/nrd (GitHub) | `https://raw.githubusercontent.com/cenk/nrd/master/nrd-last-10-days.txt` | 10 days | ~700K |
| WhoisDS | `https://whoisds.com//whois-database/newly-registered-domains/<base64-date>/nrd` | Today + 10 days back | ~70K/day |

## WhoisDS URL Format

The date is base64-encoded as `YYYY-MM-DD.zip` (with `.zip` suffix, no trailing slash or newline):

```
2026-04-20.zip  →  base64  →  MjAyNi0wNC0yMC56aXA=
```

Full URL example:
```
https://whoisds.com//whois-database/newly-registered-domains/MjAyNi0wNC0yMC56aXA=/nrd
```

Files are available ~4 days in arrears. The source tries today and up to 10 days back, collecting **all** available files (not just the first). FQDNs are deduplicated across all dates.

## Downloaded Files

Raw files are saved to `<project_root>/data/nrd/` with timestamps:

```
data/nrd/
├── 20260420_143022_nrd_github_10day.txt
├── 20260420_143024_nrd_whoisds_2026-04-19.zip
├── 20260420_143025_nrd_whoisds_2026-04-18.zip
```

WhoisDS files are **cached** — if `*nrd_whoisds_YYYY-MM-DD.zip` already exists for a date, it will be used directly and the download skipped. cenk/nrd is always re-downloaded (it is a rolling 10-day file that changes daily).

## Example Commands

```bash
ddig purge-registered --verbose
```

```bash
ddig purge-registered --dry-run --verbose
```

```bash
ddig purge-registered --source nrd --verbose
```

```bash
ddig purge-registered --source whoisds --verbose
```

## Notes

- Both feeds cover all TLDs
- cenk/nrd covers the last 10 days — only one file exists
- WhoisDS tries today and up to 10 days back — collects **all** available dates, not just the most recent
- FQDNs are deduplicated across all dates and across both feeds
- Watchlisted domains are never deleted even if they appear in the NRD feed
- Downloaded files persist in `data/nrd/` for review — clean up manually as needed