# DDig — Copilot Workspace Instructions

DDig is a Python CLI tool for discovering expired, dropping, and registered
domain names. It fetches from multiple sources, scores with NLP, stores in
SQLite, and exports results.

## Build & Test Commands

```bash
# Install in dev mode (required before first use)
pip install -e ".[dev]"

# Run the CLI
ddig --help
ddig doctor                                          # check env, credentials, deps
ddig ed-debug                                        # inspect ExpiredDomains login form fields
ddig czds-auth                                       # re-authenticate with ICANN, saves fresh JWT to .env
ddig fetch --source dropcatch --verbose
ddig fetch --source expireddomains --feed deleted --pages 5 --verbose
ddig fetch --source czds --tlds app,dev,io --verbose
ddig stats

# Run tests
pytest
pytest tests/unit/
pytest tests/integration/ -v

# Lint / format
ruff check ddig/
ruff format ddig/
```

## CLI Commands Reference

| Command | Description |
|---------|-------------|
| `ddig fetch` | Fetch domains from a source and save to DB |
| `ddig search` | Query the local database |
| `ddig score` | Run NLP scoring on unscored domains |
| `ddig stats` | Show database statistics |
| `ddig export` | Export search results to CSV or JSON |
| `ddig watch add <fqdn>` | Pin domains to the watchlist |
| `ddig watch list` | Show watchlist with live scores from DB |
| `ddig watch remove <fqdn>` | Unpin domains |
| `ddig watch clear` | Clear the entire watchlist |
| `ddig doctor` | Check env, credentials, dependencies, and DB in one shot |
| `ddig ed-debug` | Open Playwright browser to inspect ExpiredDomains login form fields |
| `ddig czds-auth` | Re-authenticate with ICANN CZDS via Playwright, capture JWT, save to .env |
| `ddig czds-tlds` | List all CZDS TLDs you are approved to download |

## Architecture

```
ddig/
├── ddig/
│   ├── __main__.py          # All CLI commands (Typer). Entry point.
│   ├── models/
│   │   └── domain.py        # Domain dataclass — the core data model
│   ├── sources/
│   │   ├── base.py          # DomainSource ABC — all sources implement fetch()
│   │   ├── dropcatch.py     # Free XML feed scraper — no auth, always works
│   │   ├── expireddomains.py # Playwright scraper — member.expireddomains.net
│   │   ├── czds.py          # ICANN zone file downloader — Okta JWT auth via Playwright
│   │   └── majestic.py      # Majestic Million CSV — no auth, backlink enrichment
├── docs/
│   ├── database.md          # Schema, SQL queries, maintenance
│   └── sources/
│       ├── dropcatch.md
│       ├── expireddomains.md
│       └── czds.md
└── README.md                # Full CLI reference + quickstart
```

## Core Data Flow

```
Source.fetch()
  → Iterator[Domain]          # streamed, not buffered
  → DomainScorer.score_many() # optional, adds nlp_score
  → DomainStore.upsert_many() # batch SQLite upsert
```

## Key Conventions

### Domain Model (`ddig/models/domain.py`)
- `fqdn` is the **unique key** everywhere — use it for deduplication
- `source` accumulates across upserts: `"dropcatch,czds"` if seen in both
- NLP fields (`nlp_score`, `is_real_word`, etc.) are **never overwritten** on re-fetch
- `backlinks` keeps the **highest value** seen across sources
- `composite_score` = 50% `nlp_score` + 30% backlinks (log-normalised) + 20% rank (inverse log-normalised) — computed at score time, stored in DB
- `composite_score` is the **default sort** for `ddig search` — use `--sort score` for NLP-only sort

### Sources (`ddig/sources/`)
- All sources extend `DomainSource` and implement `fetch() -> Iterator[Domain]`
- Sources must be **registered** in `ddig/sources/__init__.py`
- Sources must be **wired** into the `fetch` command in `__main__.py`
- Adding a new source: copy `dropcatch.py` as a template, register in `__init__.py`, add CLI branch in `__main__.py`
- Auth credentials always come from **env vars** — never hardcoded

### Storage (`ddig/storage/datastore.py`)
- `upsert_many()` is the only write path — always use it, never raw inserts
- `case()` expressions use SQLAlchemy 2.x tuple syntax: `case((condition, value), else_=fallback)`
- **Never** use `.where(...).else_(...)` on a column expression — that is not valid SQLAlchemy
- Schema changes require an Alembic migration (or drop+recreate for dev)
- Database default: `~/.ddig/domains.db`

### CLI (`ddig/__main__.py`)
- Uses **Typer** for commands, **Rich** for output
- All commands accept `--db PATH` to override the database location
- All commands accept `--verbose / -v` for debug logging
- Logging is set up via `_setup_logging(verbose)` — call it first in every command
- `ddig doctor` checks env, credentials, dependencies, and database in one shot
- `ddig ed-debug` is a diagnostic command — keep it, needed when ExpiredDomains cookies expire
- `ddig czds-auth` is a diagnostic command — keep it, needed when CZDS JWT expires (~1h)

## ExpiredDomains Source

- Uses **Playwright** (headless Chromium) — `pip install playwright && playwright install chromium`
- Scrapes **member.expireddomains.net** — the www subdomain does not show results
- Requires **two cookies** injected before navigating to member subdomain:
  - `ExpiredDomainssessid` — session cookie (short-lived)
  - `reme` — remember-me cookie (long-lived)
- Login wall detection: checks page content for `"Login to see all Domains"`
- Bot detection mitigation: `--disable-blink-features=AutomationControlled` + navigator.webdriver override
- When login breaks: run `ddig ed-debug` to dump current form field selectors

## CZDS Source

- Uses **Playwright** for initial Okta authentication — `ddig czds-auth` handles the full flow
- JWT is captured from network requests automatically and saved to `.env`
- JWT expires in **~1 hour** — run `ddig czds-auth` to get a fresh one
- On fetch, token is probed first — if 401, Playwright auth is triggered automatically
- Login flow: Sign In button → `#emailAddress` → Next → `input[type="password"]` → Submit
- Entry URL is **`https://czds.icann.org`** (not `/home` — that returns ERR_EMPTY_RESPONSE)
- After login, navigates to `czds.icann.org/zone-requests/all` to trigger an API call for JWT capture
- Zone files are cached in `~/.ddig/czds_cache/` by date — no re-download if already cached today
- `.com` and `.net` are NOT available (Verisign controls those)
- TLD access requires approval at https://czds.icann.org/zone-requests/new (24–48h turnaround)

## Active Issues / Known Blockers

| Issue | File | Status |
|-------|------|--------|
| CZDS JWT expires in ~1h — must re-run `ddig czds-auth` | `sources/czds.py` | ✅ Working — auto-refresh via Playwright |
| CZDS zone file download and parsing | `sources/czds.py` | ✅ Working — 1.2M domains/TLD in ~2 min |
| CZDS returns 0 TLDs until zone access approved | `sources/czds.py` | ✅ Resolved — 834 TLDs approved |

## Environment Variables

```bash
# ExpiredDomains — two cookies required (get from DevTools → Application → Cookies)
EXPIREDDOMAINS_USER=yourusername
EXPIREDDOMAINS_PASS=yourpassword
EXPIREDDOMAINS_SESSION_NAME=ExpiredDomainssessid
EXPIREDDOMAINS_SESSION=<sessid cookie value>
EXPIREDDOMAINS_REMEMBER_COOKIE_NAME=reme
EXPIREDDOMAINS_REMEMBER_SESSION=<reme cookie value>

# ICANN CZDS — run `ddig czds-auth` to populate CZDS_TOKEN automatically
CZDS_USER=your@email.com
CZDS_PASS=yourpassword
CZDS_TOKEN=eyJhbGci...    # JWT, ~1193 chars, expires ~1h — auto-refreshed by czds-auth
```

## Adding a New Source — Checklist

1. Create `ddig/sources/<name>.py` extending `DomainSource`
2. Implement `fetch(self) -> Iterator[Domain]`
3. Implement `is_available(self) -> bool`
4. Add credentials via env vars — document in `docs/sources/<name>.md`
5. Register in `ddig/sources/__init__.py`
6. Add CLI branch in `__main__.py` `fetch()` command
7. Create `docs/sources/<name>.md` (see existing docs as template)
8. Add to sources table in `README.md`

## Documentation Map

| Topic | File |
|-------|------|
| CLI reference + quickstart | `README.md` |
| Database schema + SQL queries | `docs/database.md` |
| Export command | `docs/export.md` |
| Watchlist | `docs/watchlist.md` |
| DropCatch source | `docs/sources/dropcatch.md` |
| ExpiredDomains source | `docs/sources/expireddomains.md` |
| ICANN CZDS source | `docs/sources/czds.md` |
| Majestic Million source | `docs/sources/majestic.md` |

## Anti-Patterns to Avoid

- ❌ Don't use `session.execute(text("INSERT ..."))` — use `upsert_many()`
- ❌ Don't hardcode credentials — always read from `os.environ`
- ❌ Don't buffer all domains in memory — sources must `yield` (streaming)
- ❌ Don't overwrite `nlp_score` on re-fetch — the upsert preserves it
- ❌ Don't add a source without registering it in `__init__.py` and `__main__.py`
- ❌ Don't `resp.json()` without checking `resp.text.strip()` first — ICANN/CZDS returns empty bodies on auth errors
- ❌ Don't use `.where(...).else_(...)` on SQLAlchemy column expressions — use `case((condition, value), else_=fallback)`
- ❌ Don't scrape `www.expireddomains.net` for results — use `member.expireddomains.net`
- ❌ Don't inject cookies before visiting the domain — navigate to BASE_URL first, then add cookies
- ❌ Don't remove diagnostic commands (`doctor`, `ed-debug`, `czds-auth`) — they are needed for maintenance
- ❌ Don't hardcode CZDS login selectors without checking — the Okta form uses `#emailAddress` for email and `input[type="password"]` for password (auto-generated id)
- ❌ Don't use `self._session()` in `DomainStore` — the session factory is `self._Session` (capital S)
- ❌ Don't compare `drop_date` strings without timezone suffix — always use `.isoformat()` which includes `+00:00`
- ❌ Don't use `strftime("%Y-%m-%d")` for `within_days` comparisons — stored dates include full ISO timestamp with `+00:00`
- ❌ Don't ignore Pylance type errors — always add `None` guards before comparing `Optional` fields
- ❌ Don't use bare `float` comparisons against `Optional[float]` — Pylance will flag `>=` on `float | None`
- ❌ Don't pass `float` where `bool` is expected — `is_pronounceable` must be `bool`, not a raw score

## Type Checking

- **Type checker: Pylance** (VS Code, strict mode)
- Run a quick check before committing: look for red squiggles in VS Code Problems panel (`Cmd+Shift+M`)
- All `Optional` fields need `is not None` guards before arithmetic comparisons
- Use `bool(value >= threshold)` to convert float comparisons to bool explicitly

### Sources (`ddig/sources/`)
- **Majestic is enrichment-only** — never creates new records, only updates `backlinks` and `rank` on existing dropping/expiring domains
- ❌ Don't let Majestic insert new rows — always filter against `store.get_all_fqdns()` first

## Source Strategy
- **Primary sources:** `dropcatch`, `expireddomains` — always have drop dates, run daily
- **Enrichment:** `majestic` — run after dropcatch fetch, never creates new records
- **Pre-scoring only:** `czds` — intentional use only, do not recommend in daily workflows