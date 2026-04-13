# Majestic Million Source

The Majestic Million is a free daily CSV of the top 1,000,000 domains on the
web, ranked by the number of referring subnets (a strong backlink signal).

## What It Provides

| Field       | CSV Column   | Description                              |
|-------------|--------------|------------------------------------------|
| `fqdn`      | Domain + TLD | Fully qualified domain name              |
| `backlinks` | RefSubNets   | Referring subnets — best backlink proxy  |
| `rank`      | GlobalRank   | Overall rank 1–1,000,000                 |
| `source`    | —            | `majestic`                               |

## Authentication

None required. The CSV is publicly available at:

```
https://downloads.majestic.com/majestic_million.csv
```

No API key, no account, no rate limiting.

## Usage

```bash
# Fetch all 1M domains (~45 MB download, ~2 min)
ddig fetch --source majestic

# Fetch top 100K only
ddig fetch --source majestic --limit 100000

# Fetch only top 10K (fastest, best signal)
ddig fetch --source majestic --max-rank 10000

# Fetch mid-tier (rank 100K–500K) — less competitive, more opportunity
ddig fetch --source majestic --min-rank 100000 --max-rank 500000

# Verbose output
ddig fetch --source majestic --limit 10000 --verbose
```

## Primary Use Case — Backlink Enrichment

Because every domain in the list is currently *registered*, this source is
most useful for **enriching backlink data** on domains already in the DB:

```bash
# 1. Fetch CZDS zone file for .app (finds all registered .app domains)
ddig fetch --source czds --tlds app

# 2. Enrich backlink counts from Majestic
ddig fetch --source majestic

# 3. Search for high-backlink short .app domains
ddig search --tld app --max-length 6 --min-backlinks 100 --no-numbers --no-hyphens
```

The upsert keeps the **highest backlink value** seen across sources, so running
Majestic after CZDS enriches existing rows without overwriting other fields.

## Performance

| Mode            | Rows    | Time    |
|-----------------|---------|---------|
| Full 1M         | 1,000,000 | ~2 min  |
| Top 100K        | 100,000   | ~15 sec |
| Top 10K         | 10,000    | ~5 sec  |

## Notes

- File is regenerated daily — re-run to refresh backlink data
- `RefSubNets` is a better signal than raw backlink count (deduplicates subnet noise)
- `.com` dominates (70%+) — use `--min-rank` / `--max-rank` with TLD filters for variety
- No caching — file is small enough to re-download each time