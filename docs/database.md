# DDig Database

DDig uses a **SQLite** database stored at `~/.ddig/domains.db` by default.

## Location

```bash
~/.ddig/domains.db          # default
/path/to/custom.db          # override with --db flag
```

## Schema

```sql
CREATE TABLE domains (
    fqdn             TEXT PRIMARY KEY NOT NULL,  -- e.g. "example.com"
    name             TEXT NOT NULL,              -- e.g. "example"
    tld              TEXT NOT NULL,              -- e.g. "com"
    length           INTEGER,                    -- len("example") = 7
    drop_date        TEXT,                       -- ISO 8601 "2026-04-15"
    expiry_date      TEXT,                       -- ISO 8601
    fetched_at       TEXT,                       -- ISO 8601 timestamp
    source           TEXT,                       -- "dropcatch", "czds", etc.
    registrar        TEXT,
    backlinks        INTEGER,
    nlp_score        REAL,                       -- 0.0 – 1.0
    is_real_word     INTEGER,                    -- 0 or 1
    word_frequency   REAL,                       -- corpus frequency
    is_pronounceable INTEGER,                    -- 0 or 1
    tags             TEXT                        -- pipe-separated "short|real_word"
);
```

## Upsert Behaviour

- `fqdn` is the **unique key** — duplicate fetches update rather than insert
- `source` **accumulates** — if a domain appears in both DropCatch and CZDS,
  source becomes `"dropcatch,czds"`
- `nlp_score` and other NLP fields are **preserved** if already scored
  (a re-fetch won't overwrite existing scores)
- `backlinks` keeps the **highest value** seen across all sources

## Direct SQLite Queries

```bash
# Open the database
sqlite3 ~/.ddig/domains.db

# Count all domains
SELECT COUNT(*) FROM domains;

# Count by source
SELECT source, COUNT(*) FROM domains GROUP BY source ORDER BY COUNT(*) DESC;

# Count by TLD
SELECT tld, COUNT(*) FROM domains GROUP BY tld ORDER BY COUNT(*) DESC LIMIT 20;

# Top scored domains
SELECT fqdn, nlp_score, tld, drop_date
FROM domains
WHERE nlp_score IS NOT NULL
ORDER BY nlp_score DESC
LIMIT 20;

# Short real-word .com domains dropping soon
SELECT fqdn, nlp_score, drop_date
FROM domains
WHERE tld = 'com'
  AND length <= 6
  AND is_real_word = 1
  AND nlp_score > 0.7
ORDER BY drop_date ASC, nlp_score DESC;

# Unscored domains (need scoring pass)
SELECT COUNT(*) FROM domains WHERE nlp_score IS NULL;

# Domains from multiple sources
SELECT fqdn, source FROM domains WHERE source LIKE '%,%';

# Export to CSV directly from SQLite
.headers on
.mode csv
.output /tmp/top_domains.csv
SELECT fqdn, tld, nlp_score, drop_date, source
FROM domains
WHERE nlp_score > 0.8
ORDER BY nlp_score DESC;
.output stdout
```

## Maintenance

```bash
# Database size
du -sh ~/.ddig/domains.db

# Vacuum (compact after large deletes)
sqlite3 ~/.ddig/domains.db "VACUUM;"

# Backup
cp ~/.ddig/domains.db ~/.ddig/domains.db.bak

# Delete all domains from a specific source
sqlite3 ~/.ddig/domains.db "DELETE FROM domains WHERE source = 'czds';"

# Reset entirely
rm ~/.ddig/domains.db
ddig fetch --source dropcatch   # recreates the schema automatically
```