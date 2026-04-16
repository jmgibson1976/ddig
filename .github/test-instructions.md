# DDig — Test Instructions

## Running Tests

```bash
# All tests
pytest

# Unit tests only (fast, no network, no Playwright)
pytest tests/unit/

# Specific module
pytest tests/unit/storage/ -v
pytest tests/unit/cli/ -v
pytest tests/unit/sources/ -v
pytest tests/unit/nlp/ -v

# Single file
pytest tests/unit/storage/test_datastore_upsert.py -v
pytest tests/unit/cli/test_search_command.py -v

# Single test
pytest tests/unit/storage/test_datastore_upsert.py::TestUpsertDeduplication::test_duplicate_fqdn_does_not_create_new_row -v
```

## Test Structure

```
tests/
└── unit/
    ├── cli/
    │   ├── test_doctor_command.py    # ddig doctor — sections, credentials, deps, DB
    │   ├── test_export_command.py    # ddig export — filters, CSV/JSON, file/stdout
    │   ├── test_fetch_command.py     # ddig fetch — source routing, options, --score flag
    │   ├── test_score_command.py     # ddig score — batching, unscored filter, options
    │   ├── test_search_command.py    # ddig search — filters passed to store.search()
    │   ├── test_stats_command.py     # ddig stats — output, store.stats() mock
    │   └── test_watch_commands.py    # ddig watch add/remove/list/clear
    ├── nlp/
    │   └── test_scorer.py            # DomainScorer — scoring, tags, edge cases
    ├── sources/
    │   ├── test_czds.py              # CZDS source — parsing, auth
    │   ├── test_dropcatch.py         # DropCatch source — XML parsing
    │   ├── test_expireddomains.py    # ExpiredDomains — login, scraping
    │   ├── test_majestic.py         # Majestic — CSV parsing, enrichment-only
    │   └── test_name.py
    └── storage/
        ├── test_datastore_search.py  # DomainStore.search() — all filter combinations
        ├── test_datastore_upsert.py  # DomainStore.upsert_many() — write path
        └── test_datastore_watchlist.py # DomainStore watch_add/remove/list/clear
```

## Fixtures & Helpers

### `store` fixture (storage tests)
All storage tests use a `tmp_path`-scoped `DomainStore`:
```python
@pytest.fixture
def store(tmp_path):
    return DomainStore(db_path=tmp_path / "test.db")
```

### `mock_store` fixture (CLI tests)
All CLI tests mock `DomainStore` via `patch("ddig.__main__.DomainStore")`:
```python
@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store
```

### `_domain()` / `_make_domain()` helpers
Each test file defines a local `_domain(**kwargs)` or `_make_domain(**kwargs)`
helper with sensible defaults. Override only what the test needs:
```python
def _domain(**kwargs) -> Domain:
    defaults = dict(fqdn="forge.io", name="forge", tld="io", source="dropcatch")
    defaults.update(kwargs)
    return Domain(**defaults)
```

## Conventions

- **Unit tests are fast** — no network, no Playwright, no real DB (use `tmp_path`)
- **CLI tests mock the store** — test command wiring, not storage logic
- **Storage tests use a real in-memory DB** — test actual SQL behaviour
- **Source tests mock HTTP/Playwright** — test parsing logic, not live sites
- **No `pytest.mark.slow`** — all unit tests must run in < 2s total
- **Test class names** match the method/feature being tested:
  - `TestWatchAdd`, `TestWatchRemove`, `TestWatchList`, `TestWatchClear`
  - `TestUpsertInsert`, `TestUpsertDeduplication`, `TestUpsertNlpPreservation`
  - `TestSearchFilters`, `TestSearchSort`, `TestSearchRankFilters`

### Domain Construction in Tests

**Always check `ddig/models/domain.py` before writing any `_domain()` helper.**

`Domain` is a `@dataclass`. Passing unknown field names or wrong types causes `TypeError` at runtime, not import time.

**The correct pattern — use `dataclasses.replace()` to override fields:**

```python
from dataclasses import replace
from ddig.models.domain import Domain

def _domain(**kwargs) -> Domain:
    base = Domain(
        fqdn   = "forge.io",
        name   = "forge",
        tld    = "io",
        source = "dropcatch",
    )
    return replace(base, **kwargs)
```

Rules:
- ✅ Construct a valid base `Domain` with required fields only
- ✅ Use `replace(base, **kwargs)` to override — Pylance will catch unknown field names at edit time
- ✅ Only `fqdn`, `name`, `tld` are truly required — `source` defaults to `""`
- ❌ Never use `Domain(**{...merged dict...})` — unknown kwargs fail silently until runtime
- ❌ Don't guess field names — read `domain.py`
- ❌ Don't pass `drop_date=datetime(...)` unless you've confirmed `Domain.drop_date` is `Optional[datetime]`

## What Each File Covers

### `test_datastore_upsert.py`
- Basic insert (single, multiple, empty list)
- Deduplication by `fqdn`
- `source` accumulation across multiple upserts
- NLP field preservation (`nlp_score`, `is_real_word`, `is_pronounceable`, `word_frequency`)
- Backlink conflict resolution (keeps highest)
- Rank conflict resolution (keeps lowest / best)
- Drop date update behaviour
- `get_all_fqdns()` return type and contents

### `test_datastore_search.py`
- All filter parameters (`tld`, `source`, `min_score`, `max_length`, `min_backlinks`,
  `min_rank`, `max_rank`, `within_days`, `real_words`, `no_hyphens`, `no_numbers`)
- All sort options (`composite`, `score`, `rank`, `backlinks`, `drop`)
- Limit
- Composite score auto-recompute when backlinks/rank arrive

### `test_datastore_watchlist.py`
- `watch_add` — single, multiple, lowercase normalisation, whitespace strip, duplicate no-op
- `watch_remove` — existing, not-found, multiple, leaves others intact
- `watch_list` — empty, entry fields, domain join, ordering
- `watch_clear` — count returned, empties list, clear then re-add

### `test_export_command.py`
- CSV/JSON to stdout
- CSV/JSON to file
- Correct headers and field values
- All filters passed to `store.search()`

### `test_search_command.py`
- Output formatting (fqdn shown, count shown, empty message)
- All filters passed to `store.search()`
- Exit codes

### `test_stats_command.py`
- Exit code zero
- Total, scored, by_source, by_tld shown in output
- `store.stats()` called once
- Empty DB shows zero

### `test_watch_commands.py`
- `watch add` — single, multiple, already-watching message, partial add
- `watch remove` — existing, not-found, multiple
- `watch list` — empty, fqdn shown, dashes when not in DB, score shown when in DB, count
- `watch clear` — `--yes` flag, prompt without flag, abort on `n`, count shown

### `test_fetch_command.py`
- Source routing — correct source class instantiated per `--source` value
- Unknown source exits non-zero
- Per-source options: feed, pages, tld, headless, tlds, max_tlds, limit, min_rank, max_rank
- `--score` flag triggers `DomainScorer.score_many()` after fetch
- `--score` not called on empty fetch result
- `store.upsert_many()` called with fetched domains
- `--db` passed to `DomainStore`
- Output shows source name and domain count

### `test_score_command.py`
- Already-scored domains filtered out before passing to scorer
- `score_many()` called with unscored domains only
- `upsert_many()` called with scored results
- Nothing scored / nothing to do message when all already scored
- `--batch-size` option respected — large sets split into correct number of calls
- `--language` passed to `DomainScorer`
- `--db` passed to `DomainStore`
- `--verbose` accepted

### `test_doctor_command.py`
- Exit code zero always
- All sections shown: Python, dotenv, Credentials, Dependencies, Database
- All credential keys shown: `EXPIREDDOMAINS_USER`, `EXPIREDDOMAINS_SESSION`, `CZDS_USER`, `CZDS_TOKEN`
- Empty credential shows "not set"
- Present credential shows `✓`
- All dependencies shown: playwright, sqlalchemy, rich, requests
- Installed dependency shows `✓`
- DB path shown, handles missing DB gracefully

### `test_name.py`
- `TestNameSourceParsing` — CSV rows → correct `Domain` fields, `drop_date` parsed, empty `traffic_data` handled, invalid date → `None`, empty fqdn row skipped
- `TestNameSourceFetch` — mocked `requests.Session.get` → yields `Domain` objects, cookies passed with correct key `REG_IDT`
- `TestNameSourceCaching` — today's cached `.csv` file skips network; `requests.Session` never called
- `TestNameSourceAuth` — 302 redirect triggers `_auth_with_playwright()`; domains returned from second successful response
- All fetch/auth tests mock `_auth_with_playwright` to avoid stdin reads during test capture
- All tests patch `ddig.env._cache` directly instead of `os.environ` — required because sources use `get_env()` not `os.environ.get()`

### `test_expireddomains.py`
- All env-dependent tests patch `ddig.env._cache` directly — required because `ExpiredDomainsSource` uses `get_env()` not `os.environ.get()`

### `test_czds.py`
- All env-dependent tests patch `ddig.env._cache` directly — required because `CZDSSource` uses `get_env()` not `os.environ.get()`