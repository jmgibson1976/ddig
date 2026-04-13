# DropCatch Source

DropCatch.com publishes daily lists of domains that are dropping (expiring and not renewed).
This is a **free, no-auth** source — no credentials required.

## Credentials

None required. DropCatch publishes signed S3 CSV downloads via a public API.

## Available Feeds

| Feed name            | Description                                        |
|----------------------|----------------------------------------------------|
| `dropping-today`     | Domains dropping today (default)                   |
| `dropping-tomorrow`  | Domains dropping tomorrow                          |
| `dropping-2`         | Domains dropping in 2 days                         |
| `dropping-3`         | Domains dropping in 3 days                         |
| `dropping-4`         | Domains dropping in 4 days                         |
| `all-auctions`       | All domains currently in DropCatch auctions        |
| `drop-auctions`      | Drop-catch auctions only                           |
| `private-sellers`    | Private seller listings                            |
| `pre-release`        | Pre-release domains                                |
| `all-backorders`     | Domains with active backorders                     |

## Usage

```bash
# Default feed (dropping today)
ddig fetch --source dropcatch

# Specific feed
ddig fetch --source dropcatch --feed dropping-tomorrow

# Fetch and score in one step
ddig fetch --source dropcatch --feed dropping-today --score

# Verbose output
ddig fetch --source dropcatch --verbose
```

## Data Fields Provided

| Field        | Description                                      |
|--------------|--------------------------------------------------|
| `fqdn`       | Fully qualified domain name                      |
| `name`       | Domain name without TLD                          |
| `tld`        | Top-level domain                                 |
| `drop_date`  | Date the domain is dropping (UTC midnight)       |
| `source`     | `dropcatch`                                      |

## Notes

- Updated daily by DropCatch
- CSV is delivered as a `.zip` archive via a signed S3 URL
- Typically returns **500–2,000 domains per feed**
- Covers `.com`, `.net`, `.org` and other major TLDs
- `drop_date` is always set — use `ddig search --within N` to filter by days until drop