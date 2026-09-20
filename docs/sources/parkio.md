# Park.io Source

Fetches expiring domains from the Park.io JSON API. No authentication required.

## API

```
https://park.io/domains/index/<tld>.json?page=<n>
```

## Supported TLDs (18)

`co`, `ly`, `gg`, `vc`, `io`, `sh`, `me`, `ag`, `us`, `lc`, `sc`, `pro`, `info`, `ac`, `je`, `bz`, `mn`, `red`

## Pagination

- Up to 200 domains per page
- Default cap: 20 pages per TLD (4,000 domains max)
- Iteration stops early if `nextPage: false`
- A warning is logged if `nextPage: true` when the cap is reached — use `--pages` to increase

## Downloaded Files

JSON responses are saved to `<project_root>/data/parkio/` with a datestamp and TLD:

```
data/parkio/
├── parkio_io_2026-04-20.json
├── parkio_co_2026-04-20.json
└── parkio_ly_2026-04-20.json
```

If today's file already exists for a TLD it is used directly and the download is skipped. Each TLD is cached separately.

## Field Mapping

| API field | Domain field |
|-----------|-------------|
| `name` | `fqdn`, `name`, `tld` |
| `date_available` | `drop_date` |
| `date_registered` | `expiry_date` |

## Example Commands

```bash
ddig fetch --source parkio --verbose
```

```bash
ddig fetch --source parkio --tld io --verbose
```

```bash
ddig fetch --source parkio --pages 5 --verbose
```

## Notes

- Some TLDs return empty or 35-byte responses on any given day — this is normal, logged at DEBUG and skipped
- Files are cached in `data/parkio/` — clean up manually as needed
- Each TLD is cached independently per day