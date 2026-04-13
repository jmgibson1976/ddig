---
agent: agent
description: >
  Scaffold a complete new DDig domain source end-to-end:
  source class, CLI wiring, registration, docs, and tests.
  Follows the Adding a New Source checklist in copilot-instructions.md exactly.
tools:
  - read_file
  - create_file
  - insert_edit_into_file
  - run_in_terminal
arguments:
  - name: source_name
    description: Snake_case name for the source e.g. godaddy, namecheap, whoisds
    required: true
  - name: auth_type
    description: "none | apikey | oauth2 | cookie | jwt"
    required: false
    default: none
  - name: description
    description: One-line description of what the source provides
    required: false
---

You are implementing a new DDig domain source called **${source_name}**.

Follow every step below in order. Do not skip steps. After each file is
created or modified, confirm what was done before moving to the next step.

## Workspace Context

Read these files before starting — they define the patterns to follow:

- `ddig/sources/base.py`          — `DomainSource` ABC to extend
- `ddig/sources/dropcatch.py`     — canonical reference implementation
- `ddig/models/domain.py`         — `Domain` dataclass (the only return type)
- `ddig/sources/__init__.py`      — registration point
- `ddig/__main__.py`              — CLI wiring (`fetch` command)
- `docs/sources/dropcatch.md`     — doc template to follow

---

## Step 1 — Read the Reference Implementation

Read `ddig/sources/dropcatch.py` in full before writing any code.
Note:
- How credentials are read from `os.environ` only — never hardcoded
- How `fetch()` uses `yield` — never buffers all domains in a list
- How `is_available()` does a lightweight HEAD/GET to check reachability
- How `log = logging.getLogger(__name__)` is used throughout
- How `Domain(name=, tld=, fqdn=, source=self.name, fetched_at=datetime.utcnow())` is constructed

---

## Step 2 — Create the Source File

Create `ddig/sources/${source_name}.py` following this structure exactly:

```python
# filepath: ddig/sources/${source_name}.py
"""
${source_name} source.

${description}

Env vars:
    # list all required env vars here
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Iterator

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models.domain import Domain
from .base import DomainSource

log = logging.getLogger(__name__)

# Constants — base URLs, endpoints
BASE_URL = ""


class ${SourceClass}Source(DomainSource):
    """
    One-paragraph docstring explaining what this source provides,
    where data comes from, and any important limitations.

    Usage::

        source = ${SourceClass}Source()
        for domain in source.fetch():
            print(domain)
    """

    name = "${source_name}"

    def __init__(self, ...) -> None:
        # Read ALL credentials from env vars
        # Set self._session = requests.Session()
        # Set reasonable defaults for timeout, max_pages etc.
        ...

    def is_available(self) -> bool:
        """Lightweight check — HEAD or GET the base URL."""
        try:
            r = requests.head(BASE_URL, timeout=5)
            return r.status_code < 500
        except requests.RequestException:
            return False

    def fetch(self) -> Iterator[Domain]:
        """
        Fetch domains and yield Domain objects.

        Must:
        - yield (not return a list)
        - set source=self.name on every Domain
        - set fetched_at=datetime.utcnow() on every Domain
        - log INFO for summary, DEBUG for per-request details
        - handle pagination if applicable
        - handle auth errors with clear error messages
        """
        ...
```

**Auth patterns by type:**

`none` — no auth needed, just `requests.Session()`.

`apikey`:
```python
self.api_key = os.environ.get("${SOURCE_UPPER}_API_KEY", "")
self._session.headers["X-Api-Key"] = self.api_key
```

`oauth2` / `jwt`:
```python
self.username = os.environ.get("${SOURCE_UPPER}_USER", "")
self.password = os.environ.get("${SOURCE_UPPER}_PASS", "")
self._token: str | None = None
# Implement _authenticate() → sets self._token and Authorization header
# Cache token; re-auth on 401
```

`cookie`:
```python
self._session_cookie = os.environ.get("${SOURCE_UPPER}_SESSION", "")
self._session.cookies.set("sessionid", self._session_cookie)
```

**Domain construction — required fields:**
```python
yield Domain(
    name       = name,           # just the label, no TLD
    tld        = tld,            # without leading dot
    fqdn       = fqdn,           # full domain e.g. "example.com"
    source     = self.name,
    fetched_at = datetime.utcnow(),
    # optional: drop_date, expiry_date, registrar, backlinks
)
```

**Retry pattern for HTTP calls:**
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10), reraise=True)
def _fetch_page(self, url: str) -> ...:
    resp = self._session.get(url, timeout=self.timeout)
    resp.raise_for_status()
    return resp
```

---

## Step 3 — Register the Source

Edit `ddig/sources/__init__.py` — add the import and `__all__` entry:

```python
# filepath: ddig/sources/__init__.py
# ...existing code...
from .${source_name} import ${SourceClass}Source
# ...existing code...
__all__ = [..., "${SourceClass}Source"]
```

---

## Step 4 — Wire into the CLI

Edit `ddig/__main__.py` — add a branch to the `fetch()` command:

```python
# filepath: ddig/__main__.py
# ...existing code...
from .sources.${source_name} import ${SourceClass}Source
# ...existing code...

# Inside the fetch() command, add:
elif source == "${source_name}":
    src = ${SourceClass}Source(
        # pass relevant CLI options
    )
```

Also update the `--source` help string to include `${source_name}`:
```python
source: str = typer.Option("dropcatch", "--source", "-s",
    help="dropcatch | expireddomains | czds | ${source_name}"),
```

---

## Step 5 — Create Documentation

Create `docs/sources/${source_name}.md` following the structure of
`docs/sources/dropcatch.md`. Must include:

- **What it is** — one paragraph
- **Credentials** — table of env vars, how to obtain each one
- **Available Feeds** — table (if applicable)
- **Usage** — copy-pasteable `ddig fetch` examples
- **Data Fields Provided** — table of fields the source populates
- **Notes** — rate limits, TLD coverage, known limitations

---

## Step 6 — Update README

Edit `README.md` — add `${source_name}` to the Sources table:

```markdown
| `${source_name}` | ${auth_type} | <volume> | <description> |
```

---

## Step 7 — Write Unit Tests

Create `tests/unit/sources/test_${source_name}.py`:

```python
"""Unit tests for ${source_name} source."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from ddig.sources.${source_name} import ${SourceClass}Source
from ddig.models.domain import Domain


class TestInit:
    def test_reads_credentials_from_env(self, monkeypatch):
        """Credentials must come from env vars, not be hardcoded."""
        monkeypatch.setenv("${SOURCE_UPPER}_API_KEY", "test-key")
        src = ${SourceClass}Source()
        assert src.api_key == "test-key"

    def test_missing_credentials_raises_on_fetch(self, monkeypatch):
        """fetch() should raise RuntimeError (not KeyError) when creds missing."""
        monkeypatch.delenv("${SOURCE_UPPER}_API_KEY", raising=False)
        src = ${SourceClass}Source()
        with pytest.raises(RuntimeError, match="credentials"):
            list(src.fetch())


class TestFetch:
    def test_yields_domain_objects(self):
        """fetch() must yield Domain instances, not dicts or strings."""
        src = ${SourceClass}Source()
        with patch.object(src, "_session") as mock_session:
            mock_session.get.return_value = MagicMock(
                status_code=200,
                text="... mock response ...",
            )
            results = list(src.fetch())
        assert all(isinstance(d, Domain) for d in results)

    def test_source_field_set_correctly(self):
        """Every yielded Domain must have source='{source_name}'."""
        src = ${SourceClass}Source()
        with patch.object(src, "_fetch_page", return_value=...):
            for domain in src.fetch():
                assert domain.source == "${source_name}"
                break

    def test_fqdn_matches_name_plus_tld(self):
        """fqdn must equal name + '.' + tld for every domain."""
        src = ${SourceClass}Source()
        with patch.object(src, "_fetch_page", return_value=...):
            for domain in src.fetch():
                assert domain.fqdn == f"{domain.name}.{domain.tld}"
                break

    def test_is_generator(self):
        """fetch() must be a generator — not return a list."""
        import inspect
        src = ${SourceClass}Source()
        assert inspect.isgeneratorfunction(src.fetch)


class TestIsAvailable:
    def test_returns_false_on_connection_error(self):
        with patch("requests.head", side_effect=Exception("connection refused")):
            src = ${SourceClass}Source()
            assert src.is_available() is False

    def test_returns_false_on_5xx(self):
        with patch("requests.head", return_value=MagicMock(status_code=503)):
            src = ${SourceClass}Source()
            assert src.is_available() is False
```

---

## Step 8 — Smoke Test

Run the source manually to confirm it works end-to-end:

```bash
# Check it's wired correctly
ddig fetch --source ${source_name} --verbose 2>&1 | head -20

# Run unit tests
pytest tests/unit/sources/test_${source_name}.py -v

# Check it appears in stats
ddig stats
```

---

## Checklist — Confirm Before Finishing

Before marking complete, verify every item:

- [ ] `ddig/sources/${source_name}.py` created — extends `DomainSource`
- [ ] `fetch()` uses `yield` — not `return list(...)`
- [ ] All credentials from `os.environ` — nothing hardcoded
- [ ] `source=self.name` on every `Domain`
- [ ] `fetched_at=datetime.utcnow()` on every `Domain`
- [ ] Registered in `ddig/sources/__init__.py`
- [ ] CLI branch added in `__main__.py` `fetch()` command
- [ ] `--source` help string updated in `__main__.py`
- [ ] `docs/sources/${source_name}.md` created
- [ ] `README.md` sources table updated
- [ ] `tests/unit/sources/test_${source_name}.py` created
- [ ] `ddig fetch --source ${source_name} --verbose` runs without import errors
- [ ] `pytest tests/unit/sources/test_${source_name}.py` passes