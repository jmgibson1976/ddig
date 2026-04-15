# Database

DDig uses a single SQLite database at `~/.ddig/domains.db`.

## Schema

### `domains` table

The primary table. One row per FQDN.

| Column            | Type    | Description |
|-------------------|---------|-------------|
| `fqdn`            | TEXT PK | Full domain e.g. `forge.io` |
| `name`            | TEXT    | SLD only e.g. `forge` |
| `tld`             | TEXT    | TLD only e.g. `io` |
| `source`          | TEXT    | Comma-separated sources e.g. `dropcatch,majestic` |
| `drop_date`       | TEXT    | ISO 8601 timestamp — when domain drops |
| `expiry_date`     | TEXT    | ISO 8601 timestamp — original expiry |
| `registrar`       | TEXT    | Last known registrar |
| `fetched_at`      | TEXT    | ISO 8601 timestamp — when last fetched |
| `nlp_score`       | REAL    | NLP quality score 0.0–1.0 — never overwritten once set |
| `composite_score` | REAL    | 50% NLP + 30% backlinks + 20% rank — recomputed on enrichment |
| `is_real_word`    | INTEGER | 1 if name is a dictionary word |
| `word_frequency`  | REAL    | Corpus frequency score |
| `is_pronounceable`| INTEGER | 1 if phonetically pronounceable |
| `tags`            | TEXT    | Pipe-separated tags e.g. `short\|real_word` |
| `backlinks`       | INTEGER | RefSubNets from Majestic — keeps highest value seen |
| `rank`            | INTEGER | GlobalRank from Majestic — keeps lowest (best) value seen |

### `watchlist` table

Pinned domains. Independent of the `domains` table.

| Column     | Type    | Description |
|------------|---------|-------------|
| `fqdn`     | TEXT PK | Full domain e.g. `forge.io` |
| `added_at` | TEXT    | ISO 8601 timestamp — when pinned |

## Upsert Behaviour

`upsert_many()` is the **only write path**. On conflict (same `fqdn`):

| Field | Behaviour |
|-------|-----------|
| `source` | Accumulates — `dropcatch` + `czds` → `dropcatch,czds` |
| `drop_date` | Always updated |
| `expiry_date` | Always updated |
| `registrar` | Always updated |
| `fetched_at` | Always updated |
| `backlinks` | Keeps highest value seen |
| `rank` | Keeps lowest (best) value seen |
| `nlp_score` | Never overwritten once set |
| `is_real_word` | Never overwritten once set |
| `is_pronounceable` | Never overwritten once set |
| `word_frequency` | Never overwritten once set |
| `tags` | Never overwritten once set |
| `composite_score` | Recomputed whenever nlp_score, backlinks, or rank changes |

## Composite Score

```
composite_score = 0.5 × nlp_score
                + 0.3 × log(backlinks + 1) / log(max_backlinks + 1)
                + 0.2 × (1 - log(rank + 1) / log(max_rank + 1))
```

- Requires `nlp_score` to be non-null — domains without NLP score get `composite_score = None`
- `backlinks` and `rank` components are 0 if null
- Default sort for `ddig search` and `ddig export`

## Direct SQL Queries

```bash
# Open the database
sqlite3 ~/.ddig/domains.db
```

```sql
-- Count all domains
SELECT COUNT(*) FROM domains;

-- Count by source
SELECT source, COUNT(*) FROM domains GROUP BY source ORDER BY COUNT(*) DESC;

-- Count by TLD
SELECT tld, COUNT(*) FROM domains GROUP BY tld ORDER BY COUNT(*) DESC LIMIT 20;

-- Top scored domains
SELECT fqdn, nlp_score, composite_score, backlinks, rank, drop_date
FROM domains
WHERE nlp_score IS NOT NULL
ORDER BY composite_score DESC
LIMIT 20;

-- Real words dropping this week
SELECT fqdn, nlp_score, drop_date
FROM domains
WHERE is_real_word = 1
  AND drop_date >= datetime('now')
  AND drop_date <= datetime('now', '+7 days')
ORDER BY nlp_score DESC;

-- Domains with backlink data
SELECT fqdn, backlinks, rank, nlp_score
FROM domains
WHERE backlinks IS NOT NULL
ORDER BY backlinks DESC
LIMIT 20;

-- Unscored domains (run ddig score to fix)
SELECT COUNT(*) FROM domains WHERE nlp_score IS NULL;

-- Watchlist
SELECT w.fqdn, w.added_at, d.nlp_score, d.composite_score, d.drop_date
FROM watchlist w
LEFT JOIN domains d ON d.fqdn = w.fqdn
ORDER BY w.added_at DESC;
```

## Maintenance

```bash
# Show database file size
ls -lh ~/.ddig/domains.db

# Vacuum (reclaim space after large deletes)
sqlite3 ~/.ddig/domains.db "VACUUM;"

# Delete all domains from a specific source
sqlite3 ~/.ddig/domains.db "DELETE FROM domains WHERE source = 'czds';"

# Delete stale domains (drop date in the past)
sqlite3 ~/.ddig/domains.db \
  "DELETE FROM domains WHERE drop_date < datetime('now');"

# Reset NLP scores (forces re-score on next ddig score)
sqlite3 ~/.ddig/domains.db \
  "UPDATE domains SET nlp_score=NULL, composite_score=NULL,
   is_real_word=NULL, word_frequency=NULL, is_pronounceable=NULL, tags=NULL;"

# Backup
cp ~/.ddig/domains.db ~/.ddig/domains.db.bak
```

## Database Path

Override with `--db` on any command:

```bash
ddig fetch --source dropcatch --db /tmp/test.db
ddig search --tld com --db /tmp/test.db
ddig stats --db /tmp/test.db
```