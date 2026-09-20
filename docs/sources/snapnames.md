# SnapNames Source

Fetches expiring and deleting domains from the SnapNames CSV download interface.

## Authentication

None required.

## Default Behaviour

Two feeds are fetched by default:

| Feed | File | Description |
|------|------|-------------|
| `allexpiring` | `allexpiring_list.csv` | All expiring domains (~213K) |
| `deleting` | `deletinglist.csv` | Deleting within next 5 days (full list) |

Domains are deduplicated across feeds by `fqdn`.

## Downloaded Files

Raw CSVs are saved to `<project_root>/data/snapnames/` with a datestamp:

```
data/snapnames/
├── snapnames_allexpiring_list_2026-04-20.csv
└── snapnames_deletinglist_2026-04-20.csv
```

If today's file already exists it is used directly and the download is skipped.

## Example Commands

```bash
# Default — fetch both feeds
ddig fetch --source snapnames --score --verbose
```

```bash
# Single feed
ddig fetch --source snapnames --feed allexpiring --verbose
```

```bash
ddig fetch --source snapnames --feed deleting --verbose
```

```bash
# Specific raw filename stem
ddig fetch --source snapnames --feed "available_Apr_19_list" --verbose
```

## Feed Reference

| Alias | Filename stem | Description |
|-------|--------------|-------------|
| `allexpiring` | `allexpiring_list` | All expiring domains |
| `deleting` | `deletinglist` | Deleting within 5 days — full list |
| *(raw stem)* | any | Pass the exact filename stem from the SnapNames UI |

## CSV Fields

| Column | Maps to |
|--------|---------|
| `Domain name` | `fqdn`, `name`, `tld` |
| `Auction end date` | `drop_date` |
| `Current bid` | *(not stored)* |

## Notes

- No auth, no rate limiting observed
- 2 preamble lines before the real CSV header — handled automatically
- Base URL: `https://www.snapnames.com/file_dl.sn?file=<stem>.csv`
- Files are cached in `data/snapnames/` — clean up manually as needed