"""Unit tests for the ExpiredDomains Playwright source."""
from __future__ import annotations

import inspect
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from ddig.sources.expireddomains import (
    ExpiredDomainsSource,
    _parse_date,
    _parse_int,
)
from ddig.models.domain import Domain


# ------------------------------------------------------------------ #
# Init                                                                #
# ------------------------------------------------------------------ #

class TestInit:
    def test_reads_credentials_from_env(self):
        with patch("ddig.env._cache", {
            "EXPIREDDOMAINS_USER": "testuser",
            "EXPIREDDOMAINS_PASS": "testpass",
            "EXPIREDDOMAINS_SESSION": "abc123",
            "EXPIREDDOMAINS_SESSION_NAME": "ExpiredDomainssessid",
            "EXPIREDDOMAINS_REMEMBER_SESSION": "rem123",
            "EXPIREDDOMAINS_REMEMBER_COOKIE_NAME": "reme",
        }):
            src = ExpiredDomainsSource()
            assert src.username == "testuser"

    def test_reads_session_cookie_from_env(self):
        with patch("ddig.env._cache", {
            "EXPIREDDOMAINS_USER": "testuser",
            "EXPIREDDOMAINS_PASS": "testpass",
            "EXPIREDDOMAINS_SESSION": "abc123",
            "EXPIREDDOMAINS_SESSION_NAME": "ExpiredDomainssessid",
            "EXPIREDDOMAINS_REMEMBER_SESSION": "rem123",
            "EXPIREDDOMAINS_REMEMBER_COOKIE_NAME": "reme",
        }):
            src = ExpiredDomainsSource()
            assert src.session_cookie == "abc123"

    def test_invalid_list_name_raises(self):
        with pytest.raises(ValueError, match="Unknown list"):
            ExpiredDomainsSource(list_name="nonexistent")

    def test_valid_list_names(self):
        for name in ("deleted", "expired", "expiring", "registered"):
            src = ExpiredDomainsSource(list_name=name)
            assert src.list_name == name

    def test_tld_strips_leading_dot(self):
        src = ExpiredDomainsSource(tld=".com")
        assert src.tld == "com"

    def test_default_list_is_deleted(self):
        src = ExpiredDomainsSource()
        assert src.list_name == "deleted"


# ------------------------------------------------------------------ #
# Playwright availability check                                       #
# ------------------------------------------------------------------ #

class TestCheckPlaywright:
    def test_raises_when_playwright_not_installed(self):
        src = ExpiredDomainsSource()
        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with pytest.raises(RuntimeError, match="Playwright is required"):
                src._check_playwright()


# ------------------------------------------------------------------ #
# URL building                                                        #
# ------------------------------------------------------------------ #

class TestBuildListUrl:
    def test_page_1_no_tld(self):
        src = ExpiredDomainsSource(list_name="deleted")
        url = src._build_list_url(1)
        assert "member.expireddomains.net" in url
        assert "combinedexpired" in url          # LIST_URLS["deleted"] = "/domains/combinedexpired/"

    def test_page_1_no_query_string(self):
        src = ExpiredDomainsSource(list_name="deleted")
        url = src._build_list_url(1)
        assert "start=" not in url               # page 1 has no offset

    def test_page_2_increments(self):
        src = ExpiredDomainsSource(list_name="deleted")
        url1 = src._build_list_url(1)
        url2 = src._build_list_url(2)
        assert url1 != url2
        assert "start=25" in url2                # page 2 = offset 25

    def test_page_3_correct_offset(self):
        src = ExpiredDomainsSource(list_name="deleted")
        url = src._build_list_url(3)
        assert "start=50" in url                 # page 3 = offset 50

    def test_tld_filter_included(self):
        src = ExpiredDomainsSource(list_name="deleted", tld="com")
        url = src._build_list_url(1)
        assert "ftlds%5B%5D=com" in url or "ftlds[]=com" in url

    def test_expired_list_url(self):
        src = ExpiredDomainsSource(list_name="expired")
        url = src._build_list_url(1)
        assert "expireddomains" in url


class TestLogin:
    def test_session_name_attribute_exists(self, expireddomains_source):
        # Attribute is session_name, not session_cookie_name
        assert hasattr(expireddomains_source, "session_name")
        assert expireddomains_source.session_name == "ExpiredDomainssessid"

    def test_has_session_cookie(self, expireddomains_source):
        assert expireddomains_source.session_cookie != ""

    def test_has_remember_cookie(self, expireddomains_source):
        assert expireddomains_source.remember_cookie != ""

    def test_session_cookie_injected_with_correct_name(self):
        src = ExpiredDomainsSource(session_cookie="mysession")
        mock_page = MagicMock()
        mock_page.context = MagicMock()
        src._login(mock_page)
        mock_page.context.add_cookies.assert_called_once()
        cookie_arg = mock_page.context.add_cookies.call_args[0][0][0]
        # Name comes from self.session_name — default is ExpiredDomainssessid
        assert cookie_arg["name"]  == "ExpiredDomainssessid"
        assert cookie_arg["value"] == "mysession"

    def test_remember_cookie_injected_with_correct_name(self):
        src = ExpiredDomainsSource(remember_cookie="myreme")
        mock_page = MagicMock()
        mock_page.context = MagicMock()
        src._login(mock_page)
        mock_page.context.add_cookies.assert_called_once()
        cookies = mock_page.context.add_cookies.call_args[0][0]
        names = [c["name"] for c in cookies]
        assert "reme" in names                   # remember_name default is "reme"

    def test_missing_credentials_raises(self):
        with patch("ddig.env._cache", {
            "EXPIREDDOMAINS_USER": "",
            "EXPIREDDOMAINS_PASS": "",
            "EXPIREDDOMAINS_SESSION": "",
            "EXPIREDDOMAINS_SESSION_NAME": "ExpiredDomainssessid",
            "EXPIREDDOMAINS_REMEMBER_SESSION": "",
            "EXPIREDDOMAINS_REMEMBER_COOKIE_NAME": "reme",
        }):
            src = ExpiredDomainsSource()
            with pytest.raises((RuntimeError, ValueError)):
                list(src.fetch())


# ------------------------------------------------------------------ #
# Parsing helpers                                                     #
# ------------------------------------------------------------------ #

class TestParseInt:
    def test_plain_integer(self):
        assert _parse_int("42") == 42

    def test_comma_formatted(self):
        assert _parse_int("1,234,567") == 1234567

    def test_dash_returns_none(self):
        assert _parse_int("-") is None

    def test_empty_returns_none(self):
        assert _parse_int("") is None

    def test_whitespace_stripped(self):
        assert _parse_int("  99  ") == 99


class TestParseDate:
    def test_iso_format(self):
        d = _parse_date("2026-04-15")
        assert d == datetime(2026, 4, 15)

    def test_dot_format(self):
        d = _parse_date("15.04.2026")
        assert d == datetime(2026, 4, 15)

    def test_slash_format(self):
        d = _parse_date("04/15/2026")
        assert d == datetime(2026, 4, 15)

    def test_dash_returns_none(self):
        assert _parse_date("-") is None

    def test_empty_returns_none(self):
        assert _parse_date("") is None

    def test_unparseable_returns_none(self):
        assert _parse_date("not a date") is None