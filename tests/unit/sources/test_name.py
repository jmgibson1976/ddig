"""Unit tests for ddig/sources/name.py — name.com expiring-domains source."""

from __future__ import annotations

import textwrap
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ddig.models.domain import Domain
from ddig.sources.name import NameSource, _is_login_redirect, _update_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain(**kwargs) -> Domain:
    base = Domain(
        fqdn   = "forge.io",
        name   = "forge",
        tld    = "io",
        source = "name",
    )
    return replace(base, **kwargs)


SAMPLE_TSV = textwrap.dedent("""\
    domain_name\tcreated_date\texpiring_date\tprice\ttld\ttraffic_data
    forge.io\t2025-01-01\t2026-04-16 02:14:33 +00:00\t72.99\tio\t4
    bankolab.com\t2025-03-03\t2026-04-17 10:00:00 +00:00\t15.99\tcom\t3
    notraffic.net\t2024-06-01\t2026-04-18 00:00:00 +00:00\t17.99\tnet\t
""")


# ---------------------------------------------------------------------------
# TestNameSourceParsing
# ---------------------------------------------------------------------------

class TestNameSourceParsing:
    def _parse_sample(self, tmp_path: Path) -> list[Domain]:
        tsv = tmp_path / "name_2026-04-16.tsv"
        tsv.write_text(SAMPLE_TSV, encoding="utf-8")
        src = NameSource()
        return list(src._parse(tsv))

    def test_yields_correct_number_of_domains(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        assert len(domains) == 3

    def test_fqdn_correct(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        assert domains[0].fqdn == "forge.io"

    def test_name_stripped_of_tld(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        assert domains[0].name == "forge"
        assert domains[1].name == "bankolab"

    def test_tld_correct(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        assert domains[0].tld == "io"
        assert domains[1].tld == "com"

    def test_source_is_name(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        for d in domains:
            assert d.source == "name"

    def test_drop_date_parsed(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        assert domains[0].drop_date is not None
        assert domains[0].drop_date == datetime(2026, 4, 16, 2, 14, 33, tzinfo=timezone.utc)

    def test_empty_traffic_data_does_not_raise(self, tmp_path: Path) -> None:
        domains = self._parse_sample(tmp_path)
        assert domains[2].fqdn == "notraffic.net"

    def test_invalid_date_yields_domain_with_no_drop_date(self, tmp_path: Path) -> None:
        tsv = tmp_path / "name_bad.tsv"
        tsv.write_text(
            "domain_name\tcreated_date\texpiring_date\tprice\ttld\ttraffic_data\n"
            "bad.com\t2025-01-01\tNOT_A_DATE\t15.99\tcom\t1\n",
            encoding="utf-8",
        )
        src     = NameSource()
        domains = list(src._parse(tsv))
        assert len(domains) == 1
        assert domains[0].drop_date is None

    def test_empty_fqdn_row_skipped(self, tmp_path: Path) -> None:
        tsv = tmp_path / "name_empty.tsv"
        tsv.write_text(
            "domain_name\tcreated_date\texpiring_date\tprice\ttld\ttraffic_data\n"
            "\t2025-01-01\t2026-04-16 00:00:00 +00:00\t15.99\tcom\t1\n"
            "good.com\t2025-01-01\t2026-04-16 00:00:00 +00:00\t15.99\tcom\t1\n",
            encoding="utf-8",
        )
        src     = NameSource()
        domains = list(src._parse(tsv))
        assert len(domains) == 1
        assert domains[0].fqdn == "good.com"


# ---------------------------------------------------------------------------
# TestNameSourceFetch
# ---------------------------------------------------------------------------

class TestNameSourceFetch:
    def test_fetch_yields_domains_from_download(self, tmp_path: Path) -> None:
        src = NameSource()

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content     = SAMPLE_TSV.encode()
        fake_resp.text        = SAMPLE_TSV

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get", return_value=fake_resp),
        ):
            domains = list(src.fetch())

        assert len(domains) == 3
        assert all(d.source == "name" for d in domains)

    def test_fetch_calls_requests_get_with_cookies(self, tmp_path: Path) -> None:
        src = NameSource()

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content     = SAMPLE_TSV.encode()
        fake_resp.text        = SAMPLE_TSV

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get", return_value=fake_resp) as mock_get,
            patch.dict("os.environ", {"NAME_SESSION": "abc123", "NAME_SESSION_NAME": "PREG_IDT"}),
        ):
            list(src.fetch())

        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert "PREG_IDT" in kwargs["cookies"]
        assert kwargs["cookies"]["PREG_IDT"] == "abc123"

    def test_fetch_domain_fqdns_correct(self, tmp_path: Path) -> None:
        src = NameSource()

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content     = SAMPLE_TSV.encode()
        fake_resp.text        = SAMPLE_TSV

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get", return_value=fake_resp),
        ):
            fqdns = [d.fqdn for d in src.fetch()]

        assert "forge.io" in fqdns
        assert "bankolab.com" in fqdns


# ---------------------------------------------------------------------------
# TestNameSourceCaching
# ---------------------------------------------------------------------------

class TestNameSourceCaching:
    def test_cached_file_skips_network(self, tmp_path: Path) -> None:
        """If today's file already exists in data/, requests.get is not called."""
        src   = NameSource()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tsv   = tmp_path / f"name_{today}.tsv"
        tsv.write_text(SAMPLE_TSV, encoding="utf-8")

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get") as mock_get,
        ):
            domains = list(src.fetch())

        mock_get.assert_not_called()
        assert len(domains) == 3

    def test_stale_file_does_not_skip_network(self, tmp_path: Path) -> None:
        """A file from a different date is not treated as a cache hit."""
        src      = NameSource()
        stale    = tmp_path / "name_2000-01-01.tsv"
        stale.write_text(SAMPLE_TSV, encoding="utf-8")

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content     = SAMPLE_TSV.encode()
        fake_resp.text        = SAMPLE_TSV

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get", return_value=fake_resp) as mock_get,
        ):
            list(src.fetch())

        mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# TestNameSourceAuth
# ---------------------------------------------------------------------------

class TestNameSourceAuth:
    def test_redirect_triggers_playwright_auth(self, tmp_path: Path) -> None:
        """A 302 response on the first download triggers _auth_with_playwright()."""
        src = NameSource()

        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.text        = ""

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.content     = SAMPLE_TSV.encode()
        success_resp.text        = SAMPLE_TSV
        success_resp.raise_for_status = MagicMock()

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get", side_effect=[redirect_resp, success_resp]),
            patch.object(src, "_auth_with_playwright", return_value={"PREG_IDT": "new_token"}) as mock_auth,
        ):
            domains = list(src.fetch())

        mock_auth.assert_called_once()
        assert len(domains) == 3

    def test_login_page_response_triggers_playwright_auth(self, tmp_path: Path) -> None:
        """A 200 that contains login page HTML also triggers re-auth."""
        src = NameSource()

        login_page_resp = MagicMock()
        login_page_resp.status_code = 200
        login_page_resp.text        = "<html><body>Please sign in to continue.</body></html>"
        login_page_resp.content     = login_page_resp.text.encode()

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.content     = SAMPLE_TSV.encode()
        success_resp.text        = SAMPLE_TSV
        success_resp.raise_for_status = MagicMock()

        with (
            patch("ddig.sources.name.DATA_DIR", tmp_path),
            patch("ddig.sources.name.requests.get", side_effect=[login_page_resp, success_resp]),
            patch.object(src, "_auth_with_playwright", return_value={"PREG_IDT": "tok"}) as mock_auth,
        ):
            list(src.fetch())

        mock_auth.assert_called_once()


# ---------------------------------------------------------------------------
# TestNameSourceIsAvailable
# ---------------------------------------------------------------------------

class TestNameSourceIsAvailable:
    def test_returns_true_when_session_set(self) -> None:
        src = NameSource()
        with patch.dict("os.environ", {"NAME_SESSION": "some_value"}):
            assert src.is_available() is True

    def test_returns_false_when_session_missing(self) -> None:
        src = NameSource()
        env = {k: v for k, v in __import__("os").environ.items() if k != "NAME_SESSION"}
        with patch.dict("os.environ", env, clear=True):
            assert src.is_available() is False

    def test_returns_false_when_session_empty_string(self) -> None:
        src = NameSource()
        with patch.dict("os.environ", {"NAME_SESSION": ""}):
            assert src.is_available() is False