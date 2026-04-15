# Export

Export search results to CSV or JSON for use in spreadsheets, registrar tools, or downstream scripts.

## Commands

```bash
# CSV to stdout
ddig export

# JSON to stdout
ddig export --format json

# Write to file
ddig export --output ~/dropping.csv
ddig export --format json --output ~/dropping.json

# With filters
ddig export --within 7 --no-hyphens --no-numbers --min-score 0.6 --output ~/results.csv

# Specific TLD + sort
ddig export --tld io --sort backlinks --limit 500 --output ~/io-domains.csv

# All filters
ddig export \
  --tld com \
  --min-score 0.7 \
  --min-backlinks 1000 \
  --max-rank 50000 \
  --within 7 \
  --no-hyphens \
  --no-numbers \
  --real-words \
  --sort composite \
  --limit 1000 \
  --output ~/best-drops.csv
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `csv` | `csv` or `json` |
| `--output` | stdout | File path to write to |
| `--tld` | all | Filter by TLD e.g. `com` |
| `--source` | all | Filter by source: `dropcatch`, `expireddomains`, `czds` |
| `--min-score` | none | Min NLP score 0.0–1.0 |
| `--max-length` | none | Max domain name length |
| `--min-backlinks` | none | Min backlink count (from Majestic enrichment) |
| `--max-rank` | none | Max Majestic GlobalRank — e.g. `10000` = top 10K only |
| `--within` | none | Dropping within N days |
| `--real-words` | off | Real English words only |
| `--no-hyphens` | off | Exclude domains with hyphens |
| `--no-numbers` | off | Exclude domains with numbers |
| `--sort` | `composite` | `composite` \| `score` \| `rank` \| `backlinks` \| `drop` |
| `--limit` | `10000` | Max results |
| `--db` | `~/.ddig/domains.db` | Override database path |

## CSV Fields

| Field | Description |
|-------|-------------|
| `fqdn` | Full domain name e.g. `forge.io` |
| `name` | SLD only e.g. `forge` |
| `tld` | TLD only e.g. `io` |
| `length` | Character length of `name` |
| `drop_date` | ISO 8601 timestamp or empty |
| `expiry_date` | ISO 8601 timestamp or empty |
| `nlp_score` | NLP quality score 0.0–1.0 |
| `composite_score` | Combined score (NLP + backlinks + rank) |
| `word_frequency` | Word frequency score |
| `is_real_word` | `True` / `False` |
| `is_pronounceable` | `True` / `False` |
| `backlinks` | RefSubNets from Majestic Million |
| `rank` | GlobalRank from Majestic Million |
| `tags` | Pipe-separated tags e.g. `short\|real_word` |
| `registrar` | Last known registrar |
| `source` | Comma-separated sources e.g. `dropcatch,majestic` |

## Notes

- `--limit` defaults to `10,000` for export (vs `50` for `ddig search`)
- JSON stdout uses plain `print` — safe to pipe or redirect
- CSV stdout uses system stdout — safe to pipe to `head`, `grep`, etc.
- Filters are identical to `ddig search` — same `store.search()` call underneath