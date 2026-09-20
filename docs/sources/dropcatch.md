# DropCatch Source

Fetches expiring and dropping domains from the DropCatch file download API.

## Authentication

None required — the API is publicly accessible.

## How It Works

Two-step signed URL flow:

1. `GET https://client.dropcatch.com/GetFileUrl?...` → returns a signed S3 URL
2. `GET <signed S3 URL>` → returns a `.csv.zip` file
3. ZIP is extracted in-memory, CSV is parsed, then saved to `data/dropcatch/`

## Default Feed

`dropping-today` — domains dropping today.

## Available Feeds

| Feed | Description |
|------|-------------|
| `dropping-today` | Dropping today (default) |
| `dropping-tomorrow` | Dropping tomorrow |
| `dropping-2` | Dropping in 2 days |
| `dropping-3` | Dropping in 3 days |
| `dropping-4` | Dropping in 4 days |
| `all-auctions` | All active auctions |
| `drop-auctions` | Drop auctions only |
| `private-sellers` | Private seller listings |
| `pre-release` | Pre-release domains |
| `all-backorders` | All backorders |

## Downloaded Files

Raw CSV (unzipped) is saved to `<project_root>/data/dropcatch/` with a datestamp:

```
data/dropcatch/
├── dropcatch_dropping-today_2026-04-20.csv
└── dropcatch_all-auctions_2026-04-20.csv
```

If today's file already exists for that feed it is used directly and both network requests are skipped. Each feed is cached separately.

## Example Commands

```bash
ddig fetch --source dropcatch --verbose
```

```bash
ddig fetch --source dropcatch --feed all-auctions --verbose
```

```bash
ddig fetch --source dropcatch --feed dropping-tomorrow --verbose
```

## CSV Fields

| Column | Maps to |
|--------|---------|
| `domain` | `name` |
| `tld` | `tld` |
| `drop date` | `drop_date` |
| `type` | *(not stored)* |

## Notes

- Retries up to 3 times with exponential backoff on network errors
- Files are cached in `data/dropcatch/` — clean up manually as needed
- Each feed is cached separately per day