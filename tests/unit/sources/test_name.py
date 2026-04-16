"""Unit tests for ddig.sources.name"""

from __future__ import annotations

import csv
import io
from datetime import timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from ddig.sources.name import NameSource


# ── Fixtures ──────────────────────────────────────────────────────────────────

CSV_HEADER = "domain_name,created_date,expiring_date,price,tld,traffic_data\n"

SAMPLE_CSV = (
    CSV_HEADER
    + "forge.io,2015-01-01,2026-05-01T00:00:00+00:00,29.99,io,1000\n"
    + "pixel.dev,2018-03-15,2026-05-02T00:00:00+00:00,14.99,dev,500\n"
    + "bright.app,2020-06-10,2026-05-03T00:00:00+00:00,9.99,app,\n"
)

INVALID_DATE_CSV = (
    CSV_HEADER
    + "baddate.com,2020-01-01,not-a-date,9.99,com,100\n"
)

EMPTY_FQDN_CSV = (
    CSV_HEADER
    + ",2020-01-01,2026-05-01T00:00:00+00:00,9.99,com,100\n"
)

ENV_PATCH = {
    "NAME_USER":              "testuser",
    "NAME_PASS":              "testpass",
    "NAME_SESSION_NAME":      "REG_IDT",
    "NAME_SESSION":           "abc123",
    "NAME_LOGIN_TIME_NAME":   "acct_login_time",
    "NAME_LOGIN_TIME":        "1776361792",
}


def _make_source() -> NameSource:
    with patch("ddig.env._cache", ENV_PATCH):
        return NameSource()


def _mock_response(content: str, status_code: int = 200) -> MagicMock:
    resp             = MagicMock()
    resp.status_code = status_code
    resp.content     = content.encode("utf-8")
    resp.text        = content
    resp.headers     = {"content-type": "text/csv"}
    return resp


# ── Parsing tests ─────────────────────────────────────────────────────────────

class TestNameSourceParsing:
    def _parse(self, csv_content: str):
        src  = _make_source()
        path = Path("/tmp/test_name_parse.csv")
        path.write_text(csv_content, encoding="utf-8")
        return list(src._parse(path))

    def test_yields_correct_number_of_domains(self):
        domains = self._parse(SAMPLE_CSV)
        assert len(domains) == 3

    def test_fqdn_correct(self):
        domains = self._parse(SAMPLE_CSV)
        assert domains[0].fqdn == "forge.io"

    def test_name_stripped_of_tld(self):
        domains = self._parse(SAMPLE_CSV)
        assert domains[0].name == "forge"

    def test_tld_correct(self):
        domains = self._parse(SAMPLE_CSV)
        assert domains[0].tld == "io"

    def test_drop_date_parsed(self):
        domains = self._parse(SAMPLE_CSV)
        assert domains[0].drop_date is not None
        assert domains[0].drop_date.tzinfo == timezone.utc

    def test_empty_traffic_data_does_not_raise(self):
        domains = self._parse(SAMPLE_CSV)
        assert domains[2].fqdn == "bright.app"

    def test_invalid_date_yields_domain_with_no_drop_date(self):
        domains = self._parse(INVALID_DATE_CSV)
        assert len(domains) == 1
        assert domains[0].drop_date is None

    def test_empty_fqdn_row_skipped(self):
        domains = self._parse(EMPTY_FQDN_CSV)
        assert len(domains) == 0


# ── Fetch tests ───────────────────────────────────────────────────────────────

class TestNameSourceFetch:
    def test_fetch_yields_domains_from_download(self, tmp_path):
        src  = _make_source()
        resp = _mock_response(SAMPLE_CSV)
        with patch("ddig.env._cache", ENV_PATCH), \
             patch("ddig.sources.name.DATA_DIR", tmp_path), \
             patch("ddig.sources.name.requests.Session") as MockSession, \
             patch.object(src, "_auth_with_playwright", return_value={"REG_IDT": "tok", "acct_login_time": "123"}):
            MockSession.return_value.get.return_value = resp
            domains = list(src.fetch())
        assert len(domains) == 3

    def test_fetch_calls_requests_get_with_cookies(self, tmp_path):
        src  = _make_source()
        resp = _mock_response(SAMPLE_CSV)
        with patch("ddig.env._cache", ENV_PATCH), \
             patch("ddig.sources.name.DATA_DIR", tmp_path), \
             patch("ddig.sources.name.requests.Session") as MockSession, \
             patch.object(src, "_auth_with_playwright", return_value={"REG_IDT": "tok", "acct_login_time": "123"}):
            MockSession.return_value.get.return_value = resp
            list(src.fetch())
        call_kwargs = MockSession.return_value.get.call_args
        cookies = call_kwargs.kwargs.get("cookies") or call_kwargs[1].get("cookies", {})
        assert "REG_IDT" in cookies

    def test_fetch_domain_fqdns_correct(self, tmp_path):
        src  = _make_source()
        resp = _mock_response(SAMPLE_CSV)
        with patch("ddig.env._cache", ENV_PATCH), \
             patch("ddig.sources.name.DATA_DIR", tmp_path), \
             patch("ddig.sources.name.requests.Session") as MockSession, \
             patch.object(src, "_auth_with_playwright", return_value={"REG_IDT": "tok", "acct_login_time": "123"}):
            MockSession.return_value.get.return_value = resp
            domains = list(src.fetch())
        assert "forge.io" in [d.fqdn for d in domains]


# ── Caching tests ─────────────────────────────────────────────────────────────

class TestNameSourceCaching:
    def test_cached_file_skips_network(self, tmp_path):
        src        = _make_source()
        cache_file = tmp_path / src._cached_path().name
        cache_file.write_text(SAMPLE_CSV, encoding="utf-8")
        with patch("ddig.env._cache", ENV_PATCH), \
             patch("ddig.sources.name.DATA_DIR", tmp_path), \
             patch("ddig.sources.name.requests.Session") as MockSession:
            domains = list(src.fetch())
        MockSession.return_value.get.assert_not_called()
        assert len(domains) == 3


# ── Auth tests ────────────────────────────────────────────────────────────────

class TestNameSourceAuth:
    def test_redirect_triggers_playwright_auth(self, tmp_path):
        src          = _make_source()
        redirect     = _mock_response(SAMPLE_CSV, status_code=302)
        success      = _mock_response(SAMPLE_CSV, status_code=200)
        mock_cookies = {"REG_IDT": "newtoken", "acct_login_time": "123456"}

        with patch("ddig.env._cache", ENV_PATCH), \
             patch("ddig.sources.name.DATA_DIR", tmp_path), \
             patch("ddig.sources.name.requests.Session") as MockSession, \
             patch.object(src, "_auth_with_playwright", return_value=mock_cookies):
            MockSession.return_value.get.side_effect = [redirect, success]
            domains = list(src.fetch())
        assert len(domains) == 3