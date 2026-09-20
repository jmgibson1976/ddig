"""Unit tests for the DropCatch source."""
from __future__ import annotations

import inspect
import io
import zipfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ddig.sources.dropcatch import DropCatchSource, _parse_date

# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

SAMPLE_CSV = """\
domain,tld,type,drop date
atlas,com,Pending Delete,2026-04-15
forge,io,Pending Delete,2026-04-16
"""

MALFORMED_CSV = """\
domain,tld,type,drop date
,com,Pending Delete,2026-04-15
valid,net,Pending Delete,2026-04-17
"""


def _make_zip(csv_content: str, filename: str = "Dropping_Domains_2026-04-13.csv") -> bytes:
    """Wrap CSV content in a zip archive as dropcatch delivers it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, csv_content)
    return buf.getvalue()


def _mock_zip_response(csv_content: str) -> MagicMock:
    zip_bytes = _make_zip(csv_content)
    resp = MagicMock()
    resp.status_code          = 200
    resp.headers              = {"Content-Type": "application/zip"}
    resp.content              = zip_bytes
    resp.raise_for_status     = MagicMock()
    return resp


def _mock_response(body: str = "{}") -> MagicMock:
    resp = MagicMock()
    resp.status_code          = 200
    resp.text                 = body
    resp.raise_for_status     = MagicMock()
    return resp


# ------------------------------------------------------------------ #
# _parse_date                                                         #
# ------------------------------------------------------------------ #

class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2026-04-15") == datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)

    def test_slash_format(self):
        assert _parse_date("04/15/2026") == datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)

    def test_short_year_format(self):
        assert _parse_date("04/15/26") == datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_date("") is None

    def test_whitespace_returns_none(self):
        assert _parse_date("   ") is None

    def test_garbage_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_returns_timezone_aware(self):
        result = _parse_date("2026-04-15")
        assert result is not None
        assert result.tzinfo is not None


# ------------------------------------------------------------------ #
# fetch() — CSV parsing                                               #
# ------------------------------------------------------------------ #

class TestFetchParsesCsv:
    def _mock_api_response(self, csv_content: str) -> tuple[MagicMock, MagicMock]:
        """Return (signed_url_response, s3_zip_response)."""
        signed = MagicMock()
        signed.status_code = 200
        signed.json.return_value = {
            "result": {
                "fileUrl":  "https://s3.example.com/fake.csv.zip",
                "fileName": "Dropping_Domains_2026-04-13.csv.zip",
            }
        }
        signed.raise_for_status = MagicMock()
        s3 = _mock_zip_response(csv_content)
        return signed, s3

    def test_yields_correct_count(self, tmp_path):
        src = DropCatchSource()
        signed, s3 = self._mock_api_response(SAMPLE_CSV)
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[signed, s3]):
            domains = list(src.fetch())
        assert len(domains) == 2

    def test_domain_fqdn(self, tmp_path):
        src = DropCatchSource()
        signed, s3 = self._mock_api_response(SAMPLE_CSV)
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[signed, s3]):
            domains = list(src.fetch())
        fqdns = {d.fqdn for d in domains}
        assert "atlas.com" in fqdns
        assert "forge.io"  in fqdns

    def test_drop_date_populated(self, tmp_path):
        src = DropCatchSource()
        signed, s3 = self._mock_api_response(SAMPLE_CSV)
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[signed, s3]):
            domains = list(src.fetch())
        atlas = next(d for d in domains if d.name == "atlas")
        assert atlas.drop_date == datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc)

    def test_skips_rows_without_domain(self, tmp_path):
        src = DropCatchSource()
        signed, s3 = self._mock_api_response(MALFORMED_CSV)
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[signed, s3]):
            domains = list(src.fetch())
        assert len(domains) == 1
        assert domains[0].fqdn == "valid.net"

    def test_plain_csv_not_zipped(self, tmp_path):
        """Verify the parser handles the zip correctly."""
        src = DropCatchSource()
        signed, s3 = self._mock_api_response(SAMPLE_CSV)
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[signed, s3]):
            domains = list(src.fetch())
        assert len(domains) == 2

    def test_source_field(self, tmp_path):
        src = DropCatchSource()
        signed, s3 = self._mock_api_response(SAMPLE_CSV)
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[signed, s3]):
            domains = list(src.fetch())
        assert all(d.source == "dropcatch" for d in domains)


# ------------------------------------------------------------------ #
# Init                                                                #
# ------------------------------------------------------------------ #

class TestInit:
    def test_default_feed(self):
        src = DropCatchSource()
        assert src.feed == "dropping-today"

    def test_custom_feed(self):
        src = DropCatchSource(feed="all-auctions")
        assert src.feed == "all-auctions"

    def test_invalid_feed_raises(self):
        with pytest.raises(ValueError, match="feed must be one of"):
            DropCatchSource(feed="nonexistent")

    def test_all_valid_feeds(self):
        feeds = [
            "all-auctions", "drop-auctions", "private-sellers", "pre-release",
            "all-backorders", "dropping-today", "dropping-tomorrow",
            "dropping-2", "dropping-3", "dropping-4",
        ]
        for feed in feeds:
            src = DropCatchSource(feed=feed)
            assert src.feed == feed

    def test_default_timeout(self):
        src = DropCatchSource()
        assert src.timeout == 60


# ------------------------------------------------------------------ #
# fetch() is a generator                                              #
# ------------------------------------------------------------------ #

class TestFetchIsGenerator:
    def test_fetch_is_generator_function(self):
        src = DropCatchSource()
        assert inspect.isgeneratorfunction(src.fetch)


# ------------------------------------------------------------------ #
# _get_signed_url                                                     #
# ------------------------------------------------------------------ #

class TestGetSignedUrl:
    def test_returns_signed_url(self):
        src  = DropCatchSource()
        resp = _mock_response(
            body='{"result": {"fileUrl": "https://s3.example.com/file.csv.zip", "fileName": "domains.csv.zip"}}'
        )
        resp.json.return_value = {
            "result": {
                "fileUrl":  "https://s3.example.com/file.csv.zip",
                "fileName": "domains.csv.zip",
            }
        }
        with patch.object(src._session, "get", return_value=resp):
            url = src._get_signed_url()
        assert url == "https://s3.example.com/file.csv.zip"

    def test_unexpected_response_raises(self):
        src  = DropCatchSource()
        resp = _mock_response(body='{"unexpected": true}')
        resp.json.return_value = {"unexpected": True}
        with patch.object(src._session, "get", return_value=resp):
            with pytest.raises((ValueError, KeyError)):
                src._get_signed_url()

    def test_dropping_today_includes_backorder_day(self):
        src = DropCatchSource(feed="dropping-today")
        assert src._config["BackorderDay"] == "DaysOut0"

    def test_auction_has_no_backorder_day(self):
        src = DropCatchSource(feed="all-auctions")
        assert src._config["BackorderDay"] is None


# ------------------------------------------------------------------ #
# Caching (_download / _local_path)                                   #
# ------------------------------------------------------------------ #

class TestCaching:
    def _signed_resp(self) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "result": {
                "fileUrl":  "https://s3.example.com/fake.csv.zip",
                "fileName": "Dropping_Domains.csv.zip",
            }
        }
        resp.raise_for_status = MagicMock()
        return resp

    def test_data_dir_created_on_init(self, tmp_path):
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path / "dropcatch"):
            DropCatchSource()
            assert (tmp_path / "dropcatch").exists()

    def test_downloads_and_saves_when_no_cache(self, tmp_path):
        src = DropCatchSource(feed="dropping-today")
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[self._signed_resp(), _mock_zip_response(SAMPLE_CSV)]):
            list(src.fetch())
        saved = list(tmp_path.glob("dropcatch_dropping-today_*.csv"))
        assert len(saved) == 1

    def test_uses_cached_file_skips_download(self, tmp_path):
        src   = DropCatchSource(feed="dropping-today")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = tmp_path / f"dropcatch_dropping-today_{today}.csv"
        cached.write_text(SAMPLE_CSV, encoding="utf-8")
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get") as mock_get:
            list(src.fetch())
        mock_get.assert_not_called()

    def test_cached_file_yields_same_domains(self, tmp_path):
        src   = DropCatchSource(feed="dropping-today")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = tmp_path / f"dropcatch_dropping-today_{today}.csv"
        cached.write_text(SAMPLE_CSV, encoding="utf-8")
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path):
            domains = list(src.fetch())
        assert len(domains) == 2

    def test_cache_filename_includes_feed_and_today(self, tmp_path):
        src   = DropCatchSource(feed="all-auctions")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[self._signed_resp(), _mock_zip_response(SAMPLE_CSV)]):
            list(src.fetch())
        saved = list(tmp_path.glob("dropcatch_all-auctions_*.csv"))
        assert saved[0].name == f"dropcatch_all-auctions_{today}.csv"

    def test_different_feeds_cached_separately(self, tmp_path):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for feed in ["dropping-today", "all-auctions"]:
            src = DropCatchSource(feed=feed)
            with patch("ddig.sources.dropcatch.DATA_DIR", tmp_path), \
                 patch.object(src._session, "get", side_effect=[self._signed_resp(), _mock_zip_response(SAMPLE_CSV)]):
                list(src.fetch())
        saved = list(tmp_path.glob("dropcatch_*.csv"))
        assert len(saved) == 2