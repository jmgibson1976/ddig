# Majestic Million Source

Enrichment-only source — never creates new records. Updates `backlinks` and
`rank` on existing domains already in the DDig database.

## Authentication

None required.

## URL

```
https://downloads.majestic.com/majestic_million.csv
```

## Columns Used

| Column | Field |
|--------|-------|
| `GlobalRank` | `rank` |
| `Domain` | `fqdn` (already the full FQDN — do not append TLD) |
| `TLD` | `tld` |
| `RefSubNets` | `backlinks` |

## Downloaded Files

Raw CSV is saved to `<project_root>/data/majestic/` with a datestamp:

```
data/majestic/
└── majestic_million_2026-04-20.csv
```

If today's file already exists it is used directly and the download is skipped (~80MB saved per run).

## Example Commands

```bash
ddig fetch --source majestic --verbose
```

```bash
ddig fetch --source majestic --limit 100000 --verbose
```

## Notes

- **Enrichment only** — Majestic never inserts new rows, only updates `backlinks` and `rank` on domains already in the DB
- `fqdn = Domain` column as-is — never construct `f"{Domain}.{TLD}"` (produces `google.com.com`)
- File is ~80MB — first run of the day downloads it, subsequent runs use the cache
- Clean up `data/majestic/` manually as needed — old dated files are not auto-deleted