"""Shared pytest fixtures for ddig tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from ddig.sources.czds import CZDSSource
from ddig.sources.dropcatch import DropCatchSource
from ddig.sources.expireddomains import ExpiredDomainsSource


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    """Return a path to a temporary SQLite database."""
    return tmp_path / "test_domains.db"


@pytest.fixture
def czds_source(tmp_path) -> CZDSSource:
    fake_token = "eyJhbGci." + "a" * 500 + ".sig"
    return CZDSSource(
        username="test@example.com",
        password="testpass",
        token=fake_token,
        cache_dir=tmp_path,
    )


@pytest.fixture
def dropcatch_source() -> DropCatchSource:
    return DropCatchSource(feed="dropping-today")


@pytest.fixture
def expireddomains_source() -> ExpiredDomainsSource:
    return ExpiredDomainsSource(
        username="testuser",
        password="testpass",
        session_cookie="testsession",
        remember_cookie="testreme",
    )