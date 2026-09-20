# Watchlist

The watchlist lets you pin domains for monitoring regardless of drop date or score.
Stored in a separate `watchlist` table in the same `~/.ddig/domains.db` — no extra files.

## Commands

```bash
# Pin one or more domains
ddig watch add forge.io cheongbong.com computerthinks.com

# Show all watched domains with live data from the domains table
ddig watch list

# Unpin one or more domains
ddig watch remove forge.io

# Clear everything (prompts for confirmation unless --yes)
ddig watch clear
ddig watch clear --yes
```

## `ddig watch list` Output

| Column    | Source |
|-----------|--------|
| FQDN      | `watchlist` table |
| Score     | `nlp_score` from `domains` table — `—` if not in DB yet |
| Backlinks | `backlinks` from `domains` table (populated by Majestic enrichment) |
| Rank      | `rank` from `domains` table |
| Drop      | `drop_date` from `domains` table |
| Added     | When you ran `ddig watch add` |

## Notes

- A domain showing `—` for all fields is in the watchlist but not yet in the DB —
  run `ddig fetch --source dropcatch` to populate it
- Watching an already-watched domain is a no-op — no error, no duplicate
- The watchlist is **independent** of the `domains` table — purging domains does not
  clear the watchlist, and clearing the watchlist does not delete domain records
- FQDNs are normalised to lowercase on `add` and `remove`