# DDig — Test Writing Instructions

## Framework & Tools

- **pytest** — all tests use pytest, never unittest directly
- **monkeypatch** — for env vars (never `os.environ` direct mutation)
- **MagicMock / patch** — for external dependencies (HTTP, Playwright, filesystem)
- **pytest.raises** — for exception assertions
- No third-party mocking libraries beyond `unittest.mock`

## File Layout

```
tests/
├── unit/
│   ├── sources/
│   │   ├── test_dropcatch.py
│   │   ├── test_expireddomains.py
│   │   └── test_czds.py
│   ├── storage/
│   │   └── test_datastore.py
│   └── nlp/
│       └── test_scorer.py
└── integration/
    └── test_fetch_pipeline.py
```

## Test Class Structure

Group tests by method/concern using classes. Every file follows this order:

```python
# ------------------------------------------------------------------ #
# Init                                                                #
# ------------------------------------------------------------------ #
class TestInit: ...

# ------------------------------------------------------------------ #
# <Method or concern>                                                 #
# ------------------------------------------------------------------ #
class TestMethodName: ...

# ------------------------------------------------------------------ #
# Parsing helpers                                                     #
# ------------------------------------------------------------------ #
class TestParseHelpers: ...
```

## Naming Conventions

| What | Convention | Example |
|------|-----------|---------|
| Test files | `test_<module>.py` | `test_czds.py` |
| Test classes | `Test<Subject>` | `TestInit`, `TestAuthenticate` |
| Test methods | `test_<what>_<condition>` | `test_fetch_returns_domains`, `test_invalid_tld_raises` |

## What to Test

### Always test:
- `__init__` reads from env vars correctly
- `__init__` keyword args override env vars
- Invalid arguments raise `ValueError` with a helpful message
- Missing required credentials raise `RuntimeError`
- `fetch()` is a generator function (`inspect.isgeneratorfunction`)
- Parsing helpers (`_parse_date`, `_parse_int`, etc.) — all edge cases
- URL / path building methods return correct strings

### Never test:
- Private Playwright browser interactions directly (mock the page object)
- Live network calls (all HTTP must be mocked)
- Filesystem side effects in unit tests (use `tmp_path` fixture if needed)

## Mocking Patterns

### Mock env vars
```python
def test_reads_from_env(self, monkeypatch):
    monkeypatch.setenv("CZDS_USER", "test@example.com")
    src = CZDSSource()
    assert src.username == "test@example.com"
```

### Mock HTTP responses
```python
from unittest.mock import MagicMock, patch

def test_download_returns_domains(self):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '["https://czds-download-api.icann.org/czds/downloads/app.zone"]'
    mock_resp.json.return_value = ["https://czds-download-api.icann.org/czds/downloads/app.zone"]
    with patch("ddig.sources.czds.requests.Session.get", return_value=mock_resp):
        ...
```

### Mock Playwright
```python
mock_page = MagicMock()
mock_page.content.return_value = "<html>results</html>"
mock_page.query_selector_all.return_value = []
```

### Mock missing optional dependency
```python
with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
    with pytest.raises(RuntimeError, match="Playwright is required"):
        src._check_playwright()
```

### Temporary files
```python
def test_cache_path(self, tmp_path):
    src = CZDSSource(cache_dir=tmp_path)
    path = src._cache_path("app")
    assert path.parent == tmp_path
    assert "app" in path.name
```

## Fixtures

Define shared fixtures in `tests/conftest.py`:

```python
# tests/conftest.py
import pytest

@pytest.fixture
def czds_source(tmp_path):
    return CZDSSource(
        username="test@example.com",
        password="testpass",
        cache_dir=tmp_path,
    )

@pytest.fixture
def dropcatch_source():
    return DropCatchSource(feed="dropping-today")
```

## Coverage Targets

| Module | Target |
|--------|--------|
| `sources/dropcatch.py` | 80% |
| `sources/expireddomains.py` | 80% |
| `sources/czds.py` | 75% |
| `sources/majestic.py` | 90% |
| `storage/datastore.py` | 85% |
| `nlp/scorer.py` | 85% |

Run coverage:
```bash
pytest --cov=ddig --cov-report=term-missing tests/unit/
```

## Anti-Patterns to Avoid

- ❌ Don't use `os.environ["KEY"] = "value"` — always use `monkeypatch.setenv`
- ❌ Don't make real HTTP requests in unit tests
- ❌ Don't test implementation details — test behaviour and outputs
- ❌ Don't assert on Rich console output — test return values and side effects
- ❌ Don't use `assert mock.called` — use `assert mock.call_count == 1` or `mock.assert_called_once_with(...)`
- ❌ Don't write one giant test method — one assertion per test where possible
- ❌ Don't use `datetime.utcnow()` — use `datetime.now(timezone.utc)` (utcnow is deprecated in Python 3.12+)