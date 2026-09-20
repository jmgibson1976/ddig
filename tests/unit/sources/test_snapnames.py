"""Unit tests for the SnapNames source."""
from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ddig.models.domain import Domain
from ddig.sources.snapnames import SnapNamesSource, DEFAULT_FEEDS, FEED_ALIASES


def _mock_csv(rows: list[dict]) -> str:
    import csv, io
    if not rows:
        return ""
    fh = io.StringIO()
    writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return fh.getvalue()


SAMPLE_ROWS = [
    {"Domain name": "example.com",   "Auction end date": "04/20/2026", "Current bid": "79"},
    {"Domain name": "forge.io",      "Auction end date": "04/20/2026", "Current bid": "79"},
    {"Domain name": "invalid",       "Auction end date": "",            "Current bid": ""},
]


# ------------------------------------------------------------------ #
# Caching (_get_feed_text / _local_path)                              #
# ------------------------------------------------------------------ #

class TestCaching:
    def test_data_dir_created_on_init(self, tmp_path):
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path / "snapnames"):
            SnapNamesSource()
            assert (tmp_path / "snapnames").exists()

    def test_downloads_and_saves_when_no_cache(self, tmp_path):
        src      = SnapNamesSource(feed="allexpiring")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _mock_csv(SAMPLE_ROWS)
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            list(src.fetch())
        saved = list(tmp_path.glob("snapnames_allexpiring_list_*.csv"))
        assert len(saved) == 1

    def test_uses_cached_file_skips_download(self, tmp_path):
        src   = SnapNamesSource(feed="allexpiring")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = tmp_path / f"snapnames_allexpiring_list_{today}.csv"
        cached.write_text(_mock_csv(SAMPLE_ROWS), encoding="utf-8")
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get") as mock_get:
            list(src.fetch())
        mock_get.assert_not_called()

    def test_cached_file_yields_same_domains(self, tmp_path):
        src   = SnapNamesSource(feed="allexpiring")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = tmp_path / f"snapnames_allexpiring_list_{today}.csv"
        cached.write_text(_mock_csv(SAMPLE_ROWS), encoding="utf-8")
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path):
            domains = list(src.fetch())
        assert len(domains) == 2  # SAMPLE_ROWS has 2 valid rows

    def test_cache_filename_includes_feed_and_today(self, tmp_path):
        src      = SnapNamesSource(feed="deleting")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _mock_csv(SAMPLE_ROWS)
        mock_resp.raise_for_status = MagicMock()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            list(src.fetch())
        saved = list(tmp_path.glob("snapnames_deletinglist_*.csv"))
        assert saved[0].name == f"snapnames_deletinglist_{today}.csv"

    def test_both_feeds_cached_separately(self, tmp_path):
        src      = SnapNamesSource()  # default — both feeds
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _mock_csv(SAMPLE_ROWS)
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            list(src.fetch())
        saved = list(tmp_path.glob("snapnames_*.csv"))
        assert len(saved) == 2


class TestInit:
    def test_default_feed_is_none(self):
        src = SnapNamesSource()
        assert src._feed is None

    def test_custom_feed_stored(self):
        src = SnapNamesSource(feed="allexpiring")
        assert src._feed == "allexpiring"

    def test_session_has_referer_header(self):
        src = SnapNamesSource()
        referer = src._session.headers.get("Referer") or ""
        assert "snapnames.com" in str(referer)


class TestResolveFeeds:
    def test_default_returns_both_feeds(self):
        src = SnapNamesSource()
        assert src._resolve_feeds() == list(DEFAULT_FEEDS)

    def test_feed_alias_resolved(self):
        src = SnapNamesSource(feed="allexpiring")
        assert src._resolve_feeds() == ["allexpiring_list"]

    def test_feed_raw_stem_passed_through(self):
        src = SnapNamesSource(feed="deletinglist")
        assert src._resolve_feeds() == ["deletinglist"]


class TestParseRow:
    def test_valid_row_yields_domain(self):
        src = SnapNamesSource()
        row = {"Domain name": "example.com", "Auction end date": "04/20/2026", "Current bid": "79"}
        domain = src._parse_row(row)
        assert domain is not None
        assert domain.fqdn == "example.com"
        assert domain.name == "example"
        assert domain.tld  == "com"

    def test_drop_date_parsed(self):
        from datetime import datetime
        src = SnapNamesSource()
        row = {"Domain name": "example.com", "Auction end date": "04/20/2026", "Current bid": "79"}
        domain = src._parse_row(row)
        assert domain is not None
        assert domain.drop_date == datetime(2026, 4, 20)

    def test_missing_drop_date_is_none(self):
        src = SnapNamesSource()
        row = {"Domain name": "example.com", "Auction end date": "", "Current bid": ""}
        domain = src._parse_row(row)
        assert domain is not None
        assert domain.drop_date is None

    def test_invalid_fqdn_returns_none(self):
        src = SnapNamesSource()
        assert src._parse_row({"Domain name": "invalid", "Auction end date": ""}) is None

    def test_empty_fqdn_returns_none(self):
        src = SnapNamesSource()
        assert src._parse_row({"Domain name": "", "Auction end date": ""}) is None

    def test_source_field_set_to_snapnames(self):
        src = SnapNamesSource()
        row = {"Domain name": "example.com", "Auction end date": "04/20/2026", "Current bid": "79"}
        domain = src._parse_row(row)
        assert domain is not None
        assert domain.source == "snapnames"

    def test_fqdn_matches_name_plus_tld(self):
        src = SnapNamesSource()
        row = {"Domain name": "forge.io", "Auction end date": "04/20/2026", "Current bid": "79"}
        domain = src._parse_row(row)
        assert domain is not None
        assert domain.fqdn == f"{domain.name}.{domain.tld}"


class TestFetch:
    def test_is_generator(self):
        assert inspect.isgeneratorfunction(SnapNamesSource.fetch)

    def test_yields_domain_objects(self, tmp_path):
        src = SnapNamesSource(feed="allexpiring")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _mock_csv(SAMPLE_ROWS)
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            results = list(src.fetch())
        assert all(isinstance(d, Domain) for d in results)

    def test_deduplicates_across_feeds(self, tmp_path):
        src = SnapNamesSource()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _mock_csv([
            {"Domain name": "example.com", "Auction end date": "04/20/2026", "Current bid": "79"},
        ])
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            results = list(src.fetch())
        fqdns = [d.fqdn for d in results]
        assert len(fqdns) == len(set(fqdns))

    def test_skips_invalid_rows(self, tmp_path):
        src = SnapNamesSource(feed="allexpiring")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _mock_csv(SAMPLE_ROWS)
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            results = list(src.fetch())
        fqdns = [d.fqdn for d in results]
        assert "invalid" not in fqdns

    def test_empty_response_yields_nothing(self, tmp_path):
        src = SnapNamesSource(feed="allexpiring")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            assert list(src.fetch()) == []

    def test_http_error_yields_nothing(self, tmp_path):
        src = SnapNamesSource(feed="allexpiring")
        with patch("ddig.sources.snapnames.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=Exception("connection error")):
            assert list(src.fetch()) == []


class TestIsAvailable:
    def test_returns_true_on_200(self):
        src = SnapNamesSource()
        with patch.object(src._session, "head", return_value=MagicMock(status_code=200)):
            assert src.is_available() is True

    def test_returns_false_on_500(self):
        src = SnapNamesSource()
        with patch.object(src._session, "head", return_value=MagicMock(status_code=500)):
            assert src.is_available() is False

    def test_returns_false_on_exception(self):
        src = SnapNamesSource()
        with patch.object(src._session, "head", side_effect=Exception("timeout")):
            assert src.is_available() is False