---
agent: ask
description: >
  Run the full DDig pipeline: fetch domains from one or more sources,
  score with NLP, search for quality candidates, and export results.
  Guides through source selection, credential checks, and filter tuning.
---

You are helping the user run the DDig domain discovery pipeline.

The full pipeline is:
  1. **Fetch** — download domains from a source into `~/.ddig/domains.db`
  2. **Score** — run NLP scoring (real words, pronounceability, frequency)
  3. **Search** — filter the database for quality candidates
  4. **Export** — save results to CSV or JSON

## Workspace Context

- CLI entry point: `ddig/__main__.py` (Typer + Rich)
- Sources: `dropcatch` (no auth), `expireddomains` (free account), `czds` (ICANN approval)
- Database: `~/.ddig/domains.db` (SQLite, unique key = `fqdn`)
- NLP scores: `0.0–1.0` — higher is more desirable
- Docs: `README.md`, `docs/sources/`, `docs/database.md`

## Step 1 — Choose a Source

Ask the user which source to use if not specified:

| Source           | Auth needed?    | Volume          | Best for                        |
|------------------|-----------------|-----------------|----------------------------------|
| `dropcatch`      | None            | ~500–2K/day     | Quick daily run, always works    |
| `expireddomains` | Free account    | ~25/page        | SEO metrics (backlinks, age)     |
| `czds`           | ICANN approval  | Millions/TLD    | Complete TLD coverage            |

## Step 2 — Check Credentials

Before generating fetch commands, verify required env vars are set:

**dropcatch** — none needed.

**expireddomains:**
```bash
echo "User: $EXPIREDDOMAINS_USER"
echo "Pass set: $([ -n "$EXPIREDDOMAINS_PASS" ] && echo yes || echo MISSING)"
# MFA accounts also need:
echo "Session: $([ -n "$EXPIREDDOMAINS_SESSION" ] && echo set || echo not set)"
```

**czds:**
```bash
echo "User: $CZDS_USER"
echo "Token length: ${#CZDS_TOKEN}"   # should be 500+ chars
# List approved TLDs before fetching:
ddig czds-tlds
```

## Step 3 — Fetch Command

Generate the appropriate fetch command based on source and user goals.

**dropcatch (recommended starting point):**
```bash
ddig fetch --source dropcatch --feed dropping-today --score --verbose
ddig fetch --source dropcatch --feed dropping-soon  --score --verbose
```

**expireddomains:**
```bash
ddig fetch --source expireddomains --feed deleted --pages 10 --score --verbose
```

**czds (after TLD approval):**
```bash
# Single TLD test first
ddig fetch --source czds --tlds app --score --verbose

# Multiple TLDs
ddig fetch --source czds --tlds app,dev,io,shop --score --verbose

# All approved TLDs (can take a long time — zone files are large)
ddig fetch --source czds --score --verbose
```

Always recommend `--score` on the fetch so scoring runs immediately.
If the user skips `--score`, remind them to run `ddig score` afterwards.

## Step 4 — Check Stats

After fetching, always show database stats:
```bash
ddig stats
```

Look for:
- `NLP scored` count — should equal `Total domains` if `--score` was used
- `By Source` — confirm the new source appears
- `By TLD` — check distribution looks sensible

## Step 5 — Search for Candidates

Suggest search commands based on the user's goal.
Ask if not clear: **"Are you looking for brandable short names, SEO-valuable expired domains, or something specific?"**

**Short brandable .com domains:**
```bash
ddig search --tld com --max-length 6 --real-words --no-hyphens --no-numbers --min-score 0.75
```

**Dropping soon (act fast):**
```bash
ddig search --within 3 --real-words --min-score 0.7 --no-hyphens
```

**Any TLD, high quality:**
```bash
ddig search --real-words --min-score 0.8 --max-length 8 --no-hyphens --no-numbers --limit 50
```

**Specific niche (e.g. tech):**
```bash
ddig search --name tech --tld io --min-score 0.6
ddig search --name app  --tld dev --min-score 0.6
```

Tune filters iteratively — if results are too few, loosen `--min-score` or increase `--max-length`.
If results are too many, tighten filters or add `--real-words`.

## Step 6 — Export

Once the user is happy with search results, export:

```bash
# CSV (default, opens in Excel/Sheets)
ddig export results.csv --tld com --min-score 0.75 --real-words --no-hyphens

# JSON (for programmatic use)
ddig export results.json --format json --min-score 0.7 --limit 5000

# Premium short candidates
ddig export premium.csv --max-length 5 --real-words --no-hyphens --no-numbers
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `0 domains fetched` from dropcatch | Feed name wrong or site down | Try `--feed dropping-soon` |
| `Login wall detected` on expireddomains | Session cookie expired | Re-copy `sessionid` cookie → `export EXPIREDDOMAINS_SESSION=...` |
| `CZDS returns 0 TLDs` | No approved TLDs yet | Visit https://czds.icann.org/zone-requests/new |
| `CZDS_TOKEN 401` | Token expired (~24h TTL) | Re-copy token from browser DevTools → `czds-api.icann.org` requests |
| `NLP scored = 0` after fetch | `--score` not used | Run `ddig score --verbose` |
| Search returns 0 results | Filters too tight | Lower `--min-score`, raise `--max-length` |

## Output Style

- Show all commands as copy-pasteable bash blocks
- After each step, confirm what the user should see before proceeding
- If a step fails, diagnose from the error output before moving on
- Keep the pipeline moving — don't stop at a blocker without suggesting the workaround