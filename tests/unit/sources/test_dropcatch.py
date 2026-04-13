"""Unit tests for the DropCatch source."""
from __future__ import annotations

import inspect
import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from ddig.sources.dropcatch import DropCatchSource, _parse_date
from ddig.models.domain import Domain


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _make_zip(csv_content: str, filename: str = "domains.csv") -> bytes:
    """Return in-memory zip bytes containing a single CSV file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, csv_content)
    return buf.getvalue()


def _mock_response(status: int = 200, body: str = "", content: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text        = body
    resp.content     = content or body.encode()
    resp.json.return_value = {}
    resp.raise_for_status = MagicMock()
    resp.headers     = {"Content-Type": "application/zip"}
    return resp


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
# fetch() parses CSV correctly                                        #
# ------------------------------------------------------------------ #

class TestFetchParsesCsv:
    CSV = "DomainName,ExpiryDate,DropDate\natlas.com,2026-01-01,2026-04-15\nforge.io,2026-02-01,2026-04-16\n"

    def _setup_mocks(self, src, csv_content):
        signed_url_resp = _mock_response(
            body='{"result": {"fileUrl": "https://s3.example.com/f.zip", "fileName": "f.csv.zip"}}'
        )
        signed_url_resp.json.return_value = {
            "result": {"fileUrl": "https://s3.example.com/f.zip", "fileName": "f.csv.zip"}
        }
        zip_resp        = _mock_response(content=_make_zip(csv_content))
        zip_resp.raise_for_status = MagicMock()
        return [signed_url_resp, zip_resp]

    def test_yields_domain_objects(self):
        src    = DropCatchSource()
        resps  = self._setup_mocks(src, self.CSV)
        with patch.object(src._session, "get", side_effect=resps):
            domains = list(src.fetch())
        assert all(isinstance(d, Domain) for d in domains)

    def test_yields_correct_count(self):
        src   = DropCatchSource()
        resps = self._setup_mocks(src, self.CSV)
        with patch.object(src._session, "get", side_effect=resps):
            domains = list(src.fetch())
        assert len(domains) == 2

    def test_domain_fqdn(self):
        src   = DropCatchSource()
        resps = self._setup_mocks(src, self.CSV)
        with patch.object(src._session, "get", side_effect=resps):
            domains = list(src.fetch())
        fqdns = {d.fqdn for d in domains}
        assert "atlas.com" in fqdns

    def test_domain_source_is_dropcatch(self):
        src   = DropCatchSource()
        resps = self._setup_mocks(src, self.CSV)
        with patch.object(src._session, "get", side_effect=resps):
            domains = list(src.fetch())
        assert all(d.source == "dropcatch" for d in domains)

    def test_skips_rows_without_domain(self):
        csv = "DomainName,ExpiryDate\n,2026-01-01\natlas.com,2026-01-01\n"
        src   = DropCatchSource()
        resps = self._setup_mocks(src, csv)
        with patch.object(src._session, "get", side_effect=resps):
            domains = list(src.fetch())
        assert len(domains) == 1

    def test_plain_csv_not_zipped(self):
        src  = DropCatchSource()
        resp_signed = _mock_response(
            body='{"result": {"fileUrl": "https://s3.example.com/f.csv", "fileName": "f.csv"}}'
        )
        resp_signed.json.return_value = {
            "result": {"fileUrl": "https://s3.example.com/f.csv", "fileName": "f.csv"}
        }
        resp_csv = _mock_response(body=self.CSV)
        resp_csv.content = self.CSV.encode()
        with patch.object(src._session, "get", side_effect=[resp_signed, resp_csv]):
            domains = list(src.fetch())
        assert len(domains) == 2


# ------------------------------------------------------------------ #
# Parsing helpers                                                     #
# ------------------------------------------------------------------ #

class TestParseDate:
    def test_iso_format(self):
        from datetime import datetime
        assert _parse_date("2026-04-15") == datetime(2026, 4, 15)

    def test_slash_format(self):
        from datetime import datetime
        assert _parse_date("04/15/2026") == datetime(2026, 4, 15)

    def test_short_year_format(self):
        from datetime import datetime
        assert _parse_date("04/15/26") == datetime(2026, 4, 15)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_date("") is None

    def test_whitespace_returns_none(self):
        assert _parse_date("   ") is None

    def test_unparseable_returns_none(self):
        assert _parse_date("not-a-date") is None