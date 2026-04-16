# DDig — Domain Discovery Tool

DDig fetches expired, dropping, and registered domain names from multiple
sources, scores them with NLP, and lets you search/export the results.

## Quick Start

```bash
# Install
pip install -e .

# Check your environment first
ddig doctor

# Fetch today's dropping domains (no credentials needed)
ddig fetch --source dropcatch --score

# Search for short, real-word .com domains
ddig search --tld com --max-length 6 --real-words --min-score 0.7

# Export results to CSV
ddig export --tld com --min-score 0.7 --output results.csv
```

## Installation

```bash
git clone https://github.com/yourname/ddig.git
cd ddig
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Copy and fill in credentials
cp .env.example .env
```

## Commands

| Command | Description |
|---------|-------------|
| `ddig fetch` | Fetch domains from a source and save to DB |
| `ddig search` | Query the local database |
| `ddig score` | Run NLP scoring on unscored domains |
| `ddig stats` | Show database statistics |
| `ddig export` | Export search results to CSV or JSON — file or stdout |
| `ddig watch add <fqdn>` | Pin one or more domains to the watchlist |
| `ddig watch list` | Show watchlist with live scores/backlinks/drop dates |
| `ddig watch remove <fqdn>` | Unpin one or more domains |
| `ddig watch clear` | Remove all watched domains |
| `ddig doctor` | Check env, credentials, dependencies, and DB |
| `ddig purge` | Remove domains with no drop date from the database |
| `ddig ed-debug` | Inspect ExpiredDomains login form fields |
| `ddig czds-auth` | Re-authenticate with ICANN CZDS |
| `ddig czds-tlds` | List all approved CZDS TLDs |

---

### `ddig doctor` — Environment Check

Run this first to verify credentials, dependencies, and database health.

```bash
ddig doctor
ddig doctor --verbose
```

Checks the following sections:

| Section | What it checks |
|---------|---------------|
| Python | Executable path and version |
| dotenv | `.env` file found and loaded |
| Credentials | All required env vars set |
| Dependencies | Python packages installed |
| CLI Tools | `git`, `gh` installed and `gh` authenticated |
| Git Hooks | `pre-push`, `prepare-commit-msg`, `post-commit` installed and executable |
| Database | DB path, total domains, scored count |

---

### `ddig ed-debug` — ExpiredDomains Form Inspector

Opens a Playwright browser, navigates to the ExpiredDomains login page, and
dumps all input field selectors. Run this when login breaks after a site
update or cookie expiry.

```bash
ddig ed-debug
```

---

### `ddig fetch` — Download Domains

```bash
ddig fetch [OPTIONS]

Options:
  -s, --source TEXT       Source to fetch from: dropcatch | expireddomains | czds | majestic
                          [default: dropcatch]
  -f, --feed TEXT         Feed/list name (source-specific)  [default: dropping-today]
  -t, --tld TEXT          TLD filter e.g. com
      --tlds TEXT         Comma-separated TLDs for czds e.g. app,dev,io
  -p, --pages INT         Max pages to scrape (expireddomains)  [default: 10]
      --max-tlds INT      Limit number of TLDs (czds, useful for testing)
      --limit INT         Max rows to fetch (majestic)  [default: 0 = all]
      --min-rank INT      Skip domains ranked below this (majestic)
      --max-rank INT      Skip domains ranked above this (majestic)
      --headless/--no-headless  Playwright headless mode  [default: headless]
      --score             Run NLP scoring immediately after fetching
      --db PATH           Database path  [default: ~/.ddig/domains.db]
  -v, --verbose           Show debug output
```

**Examples:**

```bash
# DropCatch — no credentials, fast
ddig fetch --source dropcatch
ddig fetch --source dropcatch --feed dropping-soon --score

# ExpiredDomains — requires account + cookies (see docs/sources/expireddomains.md)
ddig fetch --source expireddomains --feed deleted --pages 5 --score
ddig fetch --source expireddomains --feed deleted --pages 2 --no-headless --verbose

# ICANN CZDS — requires approved TLDs (see docs/sources/czds.md)
ddig fetch --source czds --tlds app,dev,io --score
ddig fetch --source czds --tlds app --verbose

# Majestic Million — no credentials, backlink enrichment only
ddig fetch --source majestic                          # all 1M domains
ddig fetch --source majestic --limit 10000            # top 10K only
ddig fetch --source majestic --max-rank 10000         # top 10K by rank
ddig fetch --source majestic --min-rank 100000 --max-rank 500000  # mid-tier
```

```bash
# name.com — requires session cookies in .env (auto-refreshed via Playwright)
ddig fetch --source name
ddig fetch --source name --score
```

---

### `ddig search` — Query the Database

```bash
ddig search [OPTIONS]

Options:
  -n, --name TEXT         Partial domain name match (case-insensitive)
  -t, --tld TEXT          Filter by TLD e.g. com, io, app
      --source TEXT       Filter by source: dropcatch | expireddomains | czds
      --min-score FLOAT   Minimum NLP score (0.0–1.0)
      --max-length INT    Maximum name length (not including TLD)
      --min-backlinks INT Minimum backlink count (RefSubNets from Majestic)
      --max-rank INT      Maximum Majestic GlobalRank e.g. 10000 = top 10K only
      --within INT        Dropping within N days
      --real-words        Only return real English dictionary words
      --no-hyphens        Exclude domains containing hyphens
      --no-numbers        Exclude domains containing numbers
      --sort TEXT         Sort by: composite | score | rank | backlinks | drop  [default: composite]
  -l, --limit INT         Max results to return  [default: 50]
      --db PATH           Database path
  -v, --verbose
```

**Examples:**

```bash
# Short .com domains with high NLP score
ddig search --tld com --max-length 6 --min-score 0.7

# Real English words only
ddig search --real-words --min-score 0.8 --limit 20

# Dropping within 3 days, sorted by drop date
ddig search --within 3 --real-words --no-hyphens --sort drop

# Top Majestic domains (high authority, short, clean)
ddig search --max-rank 10000 --max-length 6 --no-hyphens --no-numbers --sort rank

# Most backlinks first
ddig search --min-backlinks 1000 --no-hyphens --no-numbers --sort backlinks

# Name contains "tech"
ddig search --name tech --tld io

# Combine filters
ddig search --tld com --max-length 5 --real-words --no-numbers --no-hyphens --min-score 0.75
```

---

### `ddig score` — Run NLP Scoring

Scores all unscored domains in the database. Run after a fetch if you
didn't use `--score` on the fetch command.

```bash
ddig score [OPTIONS]

Options:
  -l, --language TEXT   Language model  [default: en]
      --db PATH         Database path
  -v, --verbose
```

```bash
ddig score
ddig score --verbose
```

**NLP Score fields:**

| Field              | Description                                      |
|--------------------|--------------------------------------------------|
| `nlp_score`        | Overall score 0.0–1.0 (higher = more desirable) |
| `is_real_word`     | True if name is a dictionary word                |
| `word_frequency`   | Corpus frequency (higher = more common word)     |
| `is_pronounceable` | True if name is phonetically pronounceable       |
| `tags`             | e.g. `short`, `real_word`, `pronounceable`       |

---

### `ddig stats` — Database Statistics

```bash
ddig stats [OPTIONS]

Options:
      --db PATH   Database path
  -v, --verbose
```

```bash
ddig stats
```

Example output:
```
        DDig Database Stats
┌──────────────────────┬──────────┐
│ Metric               │    Value │
├──────────────────────┼──────────┤
│ Total domains        │  125,432 │
│ NLP scored           │   98,210 │
│ ──────────────────── │ ──────── │
│ By Source            │          │
│   dropcatch          │   12,450 │
│   expireddomains     │    2,500 │
│   czds               │  112,982 │
│ ──────────────────── │ ──────── │
│ By TLD               │          │
│   .app               │   45,210 │
│   .dev               │   38,991 │
│   .io                │   28,781 │
└──────────────────────┴──────────┘
```

---

### `ddig export` — Export to CSV or JSON

```bash
ddig export [OUTPUT] [OPTIONS]

Arguments:
  OUTPUT      Optional output file path. Omit to print to stdout.

Options:
  -f, --format TEXT       csv or json  [default: csv]
  -t, --tld TEXT          Filter by TLD
      --source TEXT       Filter by source
      --min-score FLOAT   Minimum NLP score
      --max-length INT    Maximum name length
      --min-backlinks INT Minimum backlink count
      --max-rank INT      Maximum Majestic GlobalRank
      --within INT        Dropping within N days
      --real-words        Real words only
      --no-hyphens        Exclude hyphens
      --no-numbers        Exclude numbers
      --sort TEXT         Sort by: composite | score | rank | backlinks | drop
  -l, --limit INT         Max records to export  [default: 10000]
      --db PATH           Database path
  -v, --verbose
```

**Examples:**

```bash
# Export top .com domains to CSV file
ddig export --tld com --min-score 0.7 --real-words --output top_com.csv

# Print to stdout (pipe-friendly)
ddig export --tld io --min-score 0.8 --format csv
ddig export --format json --min-score 0.5 | jq '.[0]'

# Export all scored domains to JSON file
ddig export --format json --min-score 0.5 --limit 50000 --output domains.json

# Export short premium candidates
ddig export --max-length 5 --real-words --no-hyphens --no-numbers --output premium.csv
```

---

### `ddig watch` — Watchlist

Pin domains for monitoring regardless of drop date or score.

```bash
# Pin domains
ddig watch add forge.io cheongbong.com computerthinks.com

# Show watchlist with live scores from DB
ddig watch list

# Unpin
ddig watch remove forge.io

# Clear all (prompts for confirmation)
ddig watch clear
ddig watch clear --yes
```

See [docs/watchlist.md](docs/watchlist.md) for full details.

---

### `ddig czds-tlds` — List CZDS TLD Access

```bash
ddig czds-tlds [OPTIONS]

Options:
  -v, --verbose
```

```bash
# See which TLDs you're approved to download
ddig czds-tlds

# Request more TLDs at:
# https://czds.icann.org/zone-requests/new
```

---

### `ddig czds-auth` — ICANN Re-authentication

Refreshes the CZDS JWT automatically using Playwright. Run this when the token
expires (every ~1 hour), or let `ddig fetch --source czds` trigger it automatically.

```bash
ddig czds-auth
ddig czds-auth --verbose
```

---

## Sources

| Source           | Auth Required                    | Volume                       | Run Regularly?      | Docs                                              |
|------------------|----------------------------------|------------------------------|---------------------|---------------------------------------------------|
| `dropcatch`      | None                             | ~500K/day                    | ✅ Daily             | [docs/sources/dropcatch.md](docs/sources/dropcatch.md)           |
| `expireddomains` | Free account + two cookies       | ~25/page (free)              | ✅ Daily             | [docs/sources/expireddomains.md](docs/sources/expireddomains.md) |
| `majestic`       | None                             | Enrichment only              | ✅ After fetch       | [docs/sources/majestic.md](docs/sources/majestic.md)             |
| `czds`           | ICANN account + approval         | Millions/TLD — use carefully | ⚠️ Intentional only | [docs/sources/czds.md](docs/sources/czds.md)                     |
| `name`           | Session cookies (`NAME_SESSION`) | Full expiring list daily     | ✅ Daily             | [docs/sources/name.md](docs/sources/name.md)                     |

> **Note:** CZDS provides full TLD zone files (all registered domains), not dropping domains.
> It does not add expiry or drop date signal. Use it only to pre-score a specific TLD you are
> actively monitoring. For day-to-day use, `dropcatch` is sufficient.

## Environment Variables

Credentials are loaded from a `.env` file in the project root via
`python-dotenv`. Copy `.env.example` to `.env` and fill in your values.

```bash
cp .env.example .env
```

```bash
# ExpiredDomains — two cookies required
# Get from: DevTools → Application → Cookies → expireddomains.net
EXPIREDDOMAINS_USER=yourusername
EXPIREDDOMAINS_PASS=yourpassword
EXPIREDDOMAINS_SESSION_NAME=ExpiredDomainssessid
EXPIREDDOMAINS_SESSION=<sessid cookie value>
EXPIREDDOMAINS_REMEMBER_COOKIE_NAME=reme
EXPIREDDOMAINS_REMEMBER_SESSION=<reme cookie value>

# ICANN CZDS
CZDS_USER=your@email.com
CZDS_PASS=yourpassword
CZDS_TOKEN=eyJhbGci...   # JWT, ~1193 chars, expires ~1h — run `ddig czds-auth` to refresh

# name.com — session cookies (get from DevTools → Application → Cookies → www.name.com)
NAME_USER=yourusername
NAME_PASS=yourpassword
NAME_SESSION_NAME=REG_IDT
NAME_SESSION=<REG_IDT cookie value>
NAME_LOGIN_TIME_NAME=acct_login_time
NAME_LOGIN_TIME=<acct_login_time cookie value>
```

> ⚠️ Never use shell `export` for credentials — always use `.env`.
> ⚠️ `.env` is gitignored — never commit it.

## Database

See [docs/database.md](docs/database.md) for schema details, direct SQL
queries, and maintenance commands.

## Project Structure

```
ddig/
├── ddig/
│   ├── __main__.py          # CLI commands (Typer + Rich)
│   ├── models/
│   │   └── domain.py        # Domain dataclass
│   ├── sources/
│   │   ├── base.py          # DomainSource base class
│   │   ├── dropcatch.py     # DropCatch scraper (no auth)
│   │   ├── expireddomains.py # ExpiredDomains Playwright scraper
│   │   ├── czds.py          # ICANN CZDS zone file downloader
│   │   └── majestic.py      # Majestic Million CSV (no auth)
│   ├── storage/
│   │   └── datastore.py     # SQLite store (SQLAlchemy)
│   └── nlp/
│       └── scorer.py        # NLP scoring engine
├── docs/
│   ├── database.md          # Schema, SQL queries, maintenance
│   ├── export.md            # Export command reference
│   ├── watchlist.md         # Watchlist command reference
│   └── sources/
│       ├── dropcatch.md
│       ├── expireddomains.md
│       ├── czds.md
│       └── majestic.md
├── .env                     # Your credentials (gitignored)
├── .env.example             # Credentials template (committed)
└── README.md
```