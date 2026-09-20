# DDig — Claude Code Instructions

DDig is a Python CLI tool for discovering expired, dropping, and registered domain names.
It fetches from multiple sources, scores with NLP, stores in SQLite, and exports results.

## Build & Test

```bash
# Install in dev mode (required before first use)
pip install -e ".[dev]"

# Run tests
.venv/bin/python3 -m pytest tests/ -q
.venv/bin/python3 -m pytest tests/unit/

# Run CLI
ddig --help
ddig doctor
ddig fetch --source dropcatch --verbose
ddig fetch --source expireddomains --feed deleted --pages 5 --verbose
ddig fetch --source czds --tlds app,dev,io --verbose
ddig stats
```

## Architecture

```
ddig/
├── __main__.py          # All CLI commands (Typer + Rich) — entry point
├── env.py               # Shared env reader — always use get_env(), never os.environ.get()
├── models/domain.py     # Domain dataclass — fqdn is the unique key everywhere
├── sources/
│   ├── base.py          # DomainSource ABC + FQDNSource ABC
│   ├── dropcatch.py     # Free XML feed, no auth, always works
│   ├── expireddomains.py # Playwright scraper, member.expireddomains.net, cookie auth
│   ├── czds.py          # ICANN zone files, Okta JWT via Playwright
│   ├── majestic.py      # Enrichment only — never creates new DB rows
│   ├── name.py          # name.com, cookie auth + Playwright fallback
│   ├── snapnames.py     # CSV feeds, no auth
│   ├── parkio.py        # JSON API, no auth, 18 TLDs
│   └── nrd.py           # Newly registered domains — used by purge-registered only
├── storage/datastore.py  # SQLite via SQLAlchemy — upsert_many() is the only write path
└── nlp/scorer.py         # NLP scoring engine
tests/
└── unit/
    ├── cli/              # One file per command
    ├── nlp/              # test_scorer.py
    ├── sources/          # One file per source
    └── storage/          # Datastore method tests
docs/
├── database.md           # Schema, SQL queries, maintenance
├── export.md             # Export command reference
├── watchlist.md          # Watchlist command reference
├── prompts.md            # Copilot prompt reference
├── sources/<name>.md     # Per-source detail
└── diagrams/             # Mermaid architecture diagrams — read before structural changes
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `ddig --version` | Print version and exit |
| `ddig fetch` | Fetch domains from a source and save to DB |
| `ddig search` | Query the local database |
| `ddig score` | Run NLP scoring on unscored domains |
| `ddig stats` | Show database statistics |
| `ddig export` | Export search results to CSV or JSON |
| `ddig watch add <fqdn>` | Pin domains to the watchlist |
| `ddig watch list` | Show watchlist with live scores from DB |
| `ddig watch remove <fqdn>` | Unpin domains |
| `ddig watch clear` | Clear the entire watchlist |
| `ddig doctor` | Check env, credentials, dependencies, and DB |
| `ddig purge` | Remove domains with no drop_date |
| `ddig purge-registered` | Remove newly-registered domains using NRD feeds |
| `ddig ed-debug` | Inspect ExpiredDomains login form fields (diagnostic — keep it) |
| `ddig czds-auth` | Re-authenticate with ICANN CZDS via Playwright (diagnostic — keep it) |
| `ddig czds-tlds` | List approved CZDS TLDs |
| `ddig name-debug` | Inspect name.com login form fields (diagnostic — keep it) |

## Core Data Flow

```
Source.fetch() → Iterator[Domain] → DomainScorer.score_many() → DomainStore.upsert_many()
```

## Key Conventions

### Domain Model (`ddig/models/domain.py`)
- `fqdn` is the **unique key** everywhere — use it for deduplication
- `source` accumulates across upserts: `"dropcatch,czds"` if seen in both
- NLP fields (`nlp_score`, `is_real_word`, etc.) are **never overwritten** on re-fetch
- `backlinks` keeps the **highest value** seen across sources
- `composite_score` = 50% `nlp_score` + 30% backlinks (log-norm) + 20% rank (inverse log-norm)
- `composite_score` is the default sort for `ddig search` — use `--sort score` for NLP-only

### Sources (`ddig/sources/`)
- All sources extend `DomainSource`, implement `fetch() -> Iterator[Domain]` and `is_available() -> bool`
- Sources must be **registered** in `ddig/sources/__init__.py`
- Sources must be **wired** into the `fetch` command in `__main__.py`
- Auth credentials always come from `get_env()` — never hardcoded
- Majestic is **enrichment-only** — never creates new records, only updates `backlinks` and `rank`
- Always filter Majestic against `store.get_all_fqdns()` first — never let it insert new rows
- Adding a new source: use `dropcatch.py` as a template

### Storage (`ddig/storage/datastore.py`)
- `upsert_many()` is the only write path — always use it, never raw inserts
- `case()` expressions use SQLAlchemy 2.x tuple syntax: `case((condition, value), else_=fallback)`
- Never use `.where(...).else_(...)` on a column expression
- Database default: `~/.ddig/domains.db`

### CLI (`ddig/__main__.py`)
- Uses **Typer** for commands, **Rich** for output
- All commands accept `--db PATH` and `--verbose / -v`
- Logging set up via `_setup_logging(verbose)` — call it first in every command
- Never remove `doctor`, `ed-debug`, `czds-auth`, `name-debug` — they are maintenance commands

### Environment (`ddig/env.py`)
- `get_env(key, default="")` reads from `.env` directly via `dotenv_values()`, **never** `os.environ`
- `reload_env()` clears in-memory cache — call after `_update_env()` writes new values
- Cache is process-scoped — one read per process unless `reload_env()` is called
- Never import `dotenv_values` directly in source files — always go through `get_env()`

## Source Details

### DropCatch
- Two-step signed S3 URL flow: step 1 → `GetFileUrl` API → signed URL; step 2 → download `.csv.zip`
- Default feed: `dropping-today` — 10 feeds available
- Retries 3× with exponential backoff via `tenacity`
- CSV cached in `data/dropcatch/dropcatch_<feed>_YYYY-MM-DD.csv` — skip both requests if today's exists
- Each feed cached separately

### Majestic
- Enrichment only — filter against `store.get_all_fqdns()` before yielding anything
- `fqdn = Domain` column as-is — never construct `f"{Domain}.{TLD}"` (produces `google.com.com`)
- CSV cached in `data/majestic/majestic_million_YYYY-MM-DD.csv` — ~80MB, skip if today's exists

### name.com
- Cookie auth — `REG_IDT` + `acct_login_time` cookies from `www.name.com`
- On 302 redirect, Playwright headless re-auth triggers automatically and retries the download
- Run `ddig name-debug` when Playwright auth breaks
- CSV cached in `data/name/name_YYYY-MM-DD.csv` — skip download and Playwright auth if today's exists

### ExpiredDomains
- Uses Playwright headless Chromium — scrapes `member.expireddomains.net` (not `www.`)
- Requires two cookies injected: `ExpiredDomainssessid` (session) + `reme` (remember-me)
- Navigate to BASE_URL first, then inject cookies — don't inject before navigating
- Login wall detection: checks content for `"Login to see all Domains"`
- Bot mitigation: `--disable-blink-features=AutomationControlled` + navigator.webdriver override
- Run `ddig ed-debug` when login breaks (cookie expiry, site change)

### CZDS
- Okta JWT via Playwright — `ddig czds-auth` handles full flow, saves JWT to `.env`
- JWT expires in ~1 hour — `ddig fetch --source czds` triggers auto-refresh on 401
- Entry URL is `https://czds.icann.org` (not `/home` — returns ERR_EMPTY_RESPONSE)
- After login, navigates to `czds.icann.org/zone-requests/all` to capture JWT from network requests
- Zone files cached in `data/czds/` by date — no re-download if already cached today
- `.com` and `.net` not available (Verisign controls those)
- Don't `resp.json()` without checking `resp.text.strip()` first — CZDS returns empty bodies on auth errors

### SnapNames
- CSV feeds, no auth — two feeds by default (`allexpiring_list` + `deletinglist`), deduplicated by fqdn
- CSV has 2 preamble lines before the real header — `_fetch_feed` skips to line starting with `"Domain"`
- Columns: `Domain name`, `Current bid`, `Auction end date`
- CSV cached in `data/snapnames/snapnames_<feed>_YYYY-MM-DD.csv` — each feed cached separately

### Park.io
- JSON API at `https://park.io/domains/index/<tld>.json?page=<n>`
- 18 TLDs: co, ly, gg, vc, io, sh, me, ag, us, lc, sc, pro, info, ac, je, bz, mn, red
- Some TLDs return empty/35-byte responses — normal, logged at DEBUG, skipped
- Default cap: 20 pages per TLD — emits warning if `nextPage: true` at cap
- `date_available` → `drop_date`, `date_registered` → `expiry_date`
- JSON cached in `data/parkio/parkio_<tld>_YYYY-MM-DD.json` — each TLD cached separately

### NRD (purge-registered only)
- Two feeds: cenk/nrd (GitHub) + WhoisDS — both fetched by default, deduplicated
- cenk/nrd: rolling 10-day file, always re-downloaded
- WhoisDS: tries today and up to 10 days back, collects all available dates; ~4 days in arrears
- WhoisDS date encoded as base64 of `YYYY-MM-DD.zip` (with `.zip` suffix)
- WhoisDS cached in `data/nrd/` — skip download if `*nrd_whoisds_YYYY-MM-DD.zip` exists for that date
- Watchlisted domains are never deleted even if they appear in the NRD feed
- `FQDNSource` ABC — yields `str` (FQDNs), not `Domain` objects
- No `--days` flag — cenk/nrd is always 10 days; WhoisDS collects all available automatically

## Adding a New Source — Checklist

1. Create `ddig/sources/<name>.py` extending `DomainSource`
2. Implement `fetch(self) -> Iterator[Domain]` and `is_available(self) -> bool`
3. Register in `ddig/sources/__init__.py`
4. Add CLI branch in `__main__.py` `fetch()` command
5. Add credentials via `get_env()` — document in `docs/sources/<name>.md`
6. Create `docs/sources/<name>.md`
7. Add to sources table in `README.md`
8. Create `tests/unit/sources/test_<name>.py`
9. Update `tests/unit/cli/test_fetch_command.py` — add branch for new source
10. Update diagrams: `docs/diagrams/cli-commands.md`, `docs/diagrams/data-flow.md`, `docs/diagrams/source-class.md`
11. Add row to this file's architecture section

## Architecture Diagrams (`docs/diagrams/`)

Read before making structural changes:

| Diagram | When to consult |
|---------|----------------|
| `database-er.md` | Before schema changes or new columns |
| `data-flow.md` | Before adding a source or changing the fetch pipeline |
| `upsert-logic.md` | Before changing any `upsert_many()` merge rule |
| `source-class.md` | Before adding a source or changing `DomainStore`/`DomainScorer` API |
| `cli-commands.md` | Before adding, removing, or renaming CLI commands |
| `czds-auth-flow.md` | Before touching `czds.py` or `czds-auth` |
| `expireddomains-auth-flow.md` | Before touching `expireddomains.py` or cookie injection |
| `composite-score.md` | Before changing scoring weights or `compute_composite()` |

## Testing Conventions

- Unit tests are fast — no network, no Playwright, no real DB (use `tmp_path`)
- CLI tests mock `DomainStore` via `patch("ddig.__main__.DomainStore")` — test command wiring, not storage logic
- Storage tests use a real in-memory SQLite DB via `tmp_path` — test actual SQL behaviour
- Source tests mock HTTP/Playwright — test parsing logic, not live sites
- Test class names match the method/feature: `TestWatchAdd`, `TestUpsertDeduplication`, `TestSearchFilters`
- No `pytest.mark.slow` — all unit tests must run in < 2s total
- Never use `datetime.utcnow()` — use `datetime.now(timezone.utc)` (utcnow() deprecated in 3.12+)

### Domain Construction in Tests

Always check `ddig/models/domain.py` before writing any `_domain()` helper. Wrong field names fail at runtime, not import time.

Use `dataclasses.replace()` — never `Domain(**{...merged dict...})`:

```python
from dataclasses import replace
from ddig.models.domain import Domain

def _domain(**kwargs) -> Domain:
    base = Domain(fqdn="forge.io", name="forge", tld="io", source="dropcatch")
    return replace(base, **kwargs)
```

Patching env in source tests: patch `ddig.env._cache` directly (sources use `get_env()`, not `os.environ`):
```python
with patch("ddig.env._cache", {"CZDS_TOKEN": "fake-token"}):
    ...
```

## Anti-Patterns

- ❌ `os.environ.get()` for credentials — use `get_env()` from `ddig.env`
- ❌ `dotenv_values` imported directly in source files — use `get_env()`
- ❌ Raw SQL inserts — use `upsert_many()`
- ❌ Buffering all domains in memory — sources must `yield`
- ❌ Overwriting `nlp_score` on re-fetch — upsert preserves it
- ❌ Letting Majestic insert new rows — always filter against `store.get_all_fqdns()` first
- ❌ `f"{Domain}.{TLD}"` from Majestic — `Domain` column is already the full FQDN
- ❌ `.where(...).else_()` on SQLAlchemy column expressions — use `case((cond, val), else_=fallback)`
- ❌ Scraping `www.expireddomains.net` — use `member.expireddomains.net`
- ❌ Injecting cookies before navigating — navigate to BASE_URL first, then add cookies
- ❌ Removing `doctor`, `ed-debug`, `czds-auth`, `name-debug` — these are maintenance commands
- ❌ CZDS entry URL `/home` — use `https://czds.icann.org` (bare)
- ❌ `resp.json()` without checking `resp.text.strip()` first on CZDS responses
- ❌ `self._session()` in `DomainStore` — session factory is `self._Session` (capital S)
- ❌ `strftime("%Y-%m-%d")` for `within_days` — stored dates include full ISO timestamp with `+00:00`
- ❌ Bare `float` comparisons against `Optional[float]` — add `is not None` guards
- ❌ Passing `float` where `bool` expected — `is_pronounceable` must be `bool`, not a raw score
- ❌ `python` alias — always `python3`
- ❌ Hardcoded credentials anywhere

## Type Checking

- Type checker: **Pylance** (VS Code, strict mode)
- All `Optional` fields need `is not None` guards before arithmetic comparisons
- Use `bool(value >= threshold)` to convert float comparisons to bool explicitly

## Git Workflow

Global hooks fire automatically via `core.hooksPath = ~/.copilot/hooks`:

- `prepare-commit-msg` — auto-generates Conventional Commits message from staged diff via Copilot
- `post-commit` — auto-pushes the current branch
- `pre-push` — auto-creates a draft GitHub PR for non-default branches

Branch naming: `<type>/<short-description>` e.g. `feat/snapnames-source`, `fix/czds-auth`
Types: `feat`, `fix`, `hotfix`, `refactor`, `test`, `docs`, `chore`

## Environment Variables

```bash
# ExpiredDomains (cookies from DevTools → Application → Cookies → expireddomains.net)
EXPIREDDOMAINS_USER=yourusername
EXPIREDDOMAINS_PASS=yourpassword
EXPIREDDOMAINS_SESSION_NAME=ExpiredDomainssessid
EXPIREDDOMAINS_SESSION=<sessid cookie value>
EXPIREDDOMAINS_REMEMBER_COOKIE_NAME=reme
EXPIREDDOMAINS_REMEMBER_SESSION=<reme cookie value>

# ICANN CZDS — JWT auto-refreshed by `ddig czds-auth`
CZDS_USER=your@email.com
CZDS_PASS=yourpassword
CZDS_TOKEN=eyJhbGci...   # expires ~1h

# name.com (cookies from DevTools → Application → Cookies → www.name.com)
NAME_USER=yourusername
NAME_PASS=yourpassword
NAME_SESSION_NAME=REG_IDT
NAME_SESSION=<REG_IDT cookie value>
NAME_LOGIN_TIME_NAME=acct_login_time
NAME_LOGIN_TIME=<acct_login_time cookie value>
```

Never use shell `export` for credentials. `.env` is gitignored — never commit it.

## Source Strategy

- **Primary (run daily):** `dropcatch`, `expireddomains`, `snapnames`, `parkio` — always have drop dates
- **Enrichment (run after fetch):** `majestic` — never creates new records
- **Intentional use only:** `czds` — full TLD zone files, millions of records per TLD
