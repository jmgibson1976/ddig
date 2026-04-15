# Majestic Million Source

## Overview

Majestic Million is a **backlink enrichment source only** — it never creates new domain records. It cross-references the top 1,000,000 most-linked domains on the internet against existing dropping/expiring domains in the DB and updates their `backlinks` and `rank` fields.

## What It Does

1. Downloads the Majestic Million CSV (~15MB, no auth required)
2. Loads all existing FQDNs from the DB into a `frozenset`
3. For each Majestic row — skips if FQDN not already in DB
4. Yields only matching domains with `backlinks` (RefSubNets) and `rank` (GlobalRank)
5. `upsert_many()` updates `backlinks` (highest wins) and `rank` (lowest wins) and recomputes `composite_score`

## What It Does NOT Do

- ❌ Does not create new records
- ❌ Does not insert registered domains (google.com, facebook.com etc.)
- ❌ Does not overwrite `nlp_score` or any NLP fields

## Usage

```bash
# Enrich existing dropping domains with backlink data
ddig fetch --source majestic --verbose
```

## Feed

| Property | Value |
|----------|-------|
| URL | `https://downloads.majestic.com/majestic_million.csv` |
| Format | CSV |
| Auth | None |
| Size | ~15MB |
| Frequency | Updated daily |

## Fields Populated

| Field | Source Column | Merge Rule |
|-------|--------------|------------|
| `backlinks` | `RefSubNets` | Highest value kept |
| `rank` | `GlobalRank` | Lowest (best) value kept |
| `composite_score` | Computed | Recomputed after backlinks/rank update |

## Effect on `composite_score`

After enrichment, `composite_score` is automatically recomputed for any domain that gains backlinks or rank data:

```
composite = nlp_score × 0.50
          + log_normalise(backlinks) × 0.30
          + inverse_log_normalise(rank) × 0.20
```

Domains with Majestic data will score higher than NLP-only domains and float to the top of `ddig search --sort composite`.