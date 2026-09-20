# DDig — Database Entity-Relationship Diagram

```mermaid
erDiagram
    domains {
        INTEGER id PK "autoincrement"
        STRING  fqdn       "UNIQUE NOT NULL — primary key for all logic"
        STRING  name       "NOT NULL — label without TLD"
        STRING  tld        "NOT NULL — e.g. com, io, dev"
        STRING  expiry_date "ISO-8601 UTC or NULL"
        STRING  drop_date   "ISO-8601 UTC or NULL — indexed"
        STRING  source      "comma-separated accumulator e.g. dropcatch,czds"
        STRING  registrar   "nullable"
        INTEGER backlinks   "nullable — highest value kept on upsert"
        INTEGER rank        "nullable — GlobalRank, lower = better"
        FLOAT   nlp_score        "nullable — never overwritten once set"
        FLOAT   composite_score  "nullable — 50% nlp + 30% backlinks + 20% rank"
        INTEGER is_real_word     "0/1 bool, nullable — never overwritten"
        FLOAT   word_frequency   "nullable — never overwritten"
        INTEGER is_pronounceable "0/1 bool, nullable — never overwritten"
        TEXT    tags        "JSON array e.g. ['short','english-word']"
        STRING  fetched_at  "ISO-8601 UTC — updated every upsert"
    }

    watchlist {
        STRING fqdn     PK "NOT NULL — logical FK to domains.fqdn"
        STRING added_at    "ISO-8601 UTC — when pinned"
    }

    domains ||--o| watchlist : "fqdn (logical join — no hard FK in SQLite)"
```

### Indexes

| Index name       | Column(s)    | Purpose                        |
|------------------|--------------|--------------------------------|
| `idx_tld`        | `tld`        | Filter by TLD                  |
| `idx_name`       | `name`       | Name search / partial match    |
| `idx_expiry`     | `expiry_date`| Future: expiry-based queries   |
| `idx_drop`       | `drop_date`  | `within_days` filter           |
| `idx_nlp_score`  | `nlp_score`  | `min_score` filter             |
| `idx_source`     | `source`     | Source filter                  |
| `idx_backlinks`  | `backlinks`  | `min_backlinks` filter         |
| `idx_rank`       | `rank`       | `min_rank` / `max_rank` filter |

### Notes
- `domains.fqdn` is the **only** deduplication key — never use `id` for business logic.
- `watchlist.fqdn` has no SQLite `FOREIGN KEY` constraint, but is always joined to `domains` in `watch_list()`.
- `source` is **not** normalised — it is a comma-separated string intentionally, for simplicity and append performance.