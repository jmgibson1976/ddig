# DropCatch Source

DropCatch.com publishes daily lists of domains that are dropping (expiring and not renewed).
This is a **free, no-auth** source — no credentials required.

## Credentials

None required. DropCatch publishes public XML feeds.

## Available Feeds

| Feed name        | Description                              |
|------------------|------------------------------------------|
| `dropping-today` | Domains dropping today (default)         |
| `dropping-soon`  | Domains dropping in the next few days    |
| `auction`        | Domains currently in DropCatch auctions  |
| `backorder`      | Domains with active backorders           |

## Usage

```bash
# Default feed (dropping today)
ddig fetch --source dropcatch

# Specific feed
ddig fetch --source dropcatch --feed dropping-soon

# Fetch and score in one step
ddig fetch --source dropcatch --feed dropping-today --score

# Verbose output
ddig fetch --source dropcatch --verbose
```

## Data Fields Provided

| Field        | Description                        |
|--------------|------------------------------------|
| `fqdn`       | Fully qualified domain name        |
| `name`       | Domain name without TLD            |
| `tld`        | Top-level domain                   |
| `drop_date`  | Date the domain is dropping        |
| `source`     | `dropcatch`                        |

## Notes

- Updated daily by DropCatch
- No rate limiting needed — XML feed is a single request
- Typically returns **100–2,000 domains per feed**
- Only `.com`, `.net`, `.org` and a few other major TLDs