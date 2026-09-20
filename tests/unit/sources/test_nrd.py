"""Unit tests for the NRD source."""
from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from ddig.sources.nrd import NRDSource, _whoisds_url, NRD_GITHUB_URL


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _mock_response(text: str = "", status: int = 200) -> MagicMock:
    resp             = MagicMock()
    resp.status_code = status
    resp.text        = text
    resp.content     = text.encode()
    resp.raise_for_status = MagicMock()
    return resp


def _mock_zip_response(lines: list[str]) -> MagicMock:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("domain-names.txt", "\n".join(lines))
    content          = buf.getvalue()
    resp             = MagicMock()
    resp.status_code = 200
    resp.content     = content
    resp.raise_for_status = MagicMock()
    return resp


SAMPLE_FQDNS = "forge.io\natlas.me\nexample.com\n"


# ------------------------------------------------------------------
# TestInit
# ------------------------------------------------------------------

class TestInit:
    def test_default_sources_are_both(self):
        src = NRDSource()
        assert src._sources == ["nrd", "whoisds"]

    def test_custom_sources(self):
        src = NRDSource(sources=["nrd"])
        assert src._sources == ["nrd"]

    def test_data_dir_created(self, tmp_path):
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path / "nrd"):
            NRDSource()
            assert (tmp_path / "nrd").exists()


# ------------------------------------------------------------------
# TestWhoisdsUrl
# ------------------------------------------------------------------

class TestWhoisdsUrl:
    def test_url_contains_base64_date_with_zip(self):
        from datetime import datetime, timezone
        import base64
        dt      = datetime(2026, 4, 19, tzinfo=timezone.utc)
        url     = _whoisds_url(dt)
        encoded = base64.b64encode(b"2026-04-19.zip").decode()
        assert encoded in url

    def test_url_ends_with_nrd(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 19, tzinfo=timezone.utc)
        assert _whoisds_url(dt).endswith("/nrd")

    def test_no_slash_suffix_in_encoding(self):
        from datetime import datetime, timezone
        import base64
        dt      = datetime(2026, 4, 19, tzinfo=timezone.utc)
        url     = _whoisds_url(dt)
        bad_encoded = base64.b64encode(b"2026-04-19/").decode()
        assert bad_encoded not in url


# ------------------------------------------------------------------
# TestFetchGitHub
# ------------------------------------------------------------------

class TestFetchGitHub:
    def test_yields_fqdns(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response(SAMPLE_FQDNS)):
                results = list(src.fetch())
        assert "forge.io" in results
        assert "atlas.me" in results
        assert "example.com" in results

    def test_deduplicates(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response("forge.io\nforge.io\n")):
                results = list(src.fetch())
        assert results.count("forge.io") == 1

    def test_skips_comments_and_blanks(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response("# comment\n\nforge.io\n")):
                results = list(src.fetch())
        assert results == ["forge.io"]

    def test_skips_entries_without_dot(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response("notadomain\nforge.io\n")):
                results = list(src.fetch())
        assert "notadomain" not in results
        assert "forge.io" in results

    def test_empty_response_yields_nothing(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response("")):
                assert list(src.fetch()) == []

    def test_http_error_yields_nothing(self, tmp_path):
        resp = _mock_response("", status=500)
        resp.raise_for_status.side_effect = Exception("500")
        src  = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=resp):
                assert list(src.fetch()) == []

    def test_uses_correct_url(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response(SAMPLE_FQDNS)) as mock_get:
                list(src.fetch())
        mock_get.assert_called_once_with(NRD_GITHUB_URL, timeout=60)

    def test_saves_raw_file(self, tmp_path):
        src = NRDSource(sources=["nrd"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_response(SAMPLE_FQDNS)):
                list(src.fetch())
        assert len(list(tmp_path.glob("*nrd_github*.txt"))) == 1


# ------------------------------------------------------------------
# TestFetchWhoisDS
# ------------------------------------------------------------------

class TestFetchWhoisDS:
    def test_yields_fqdns_from_first_valid_date(self, tmp_path):
        src = NRDSource(sources=["whoisds"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_zip_response(["forge.io", "atlas.me"])):
                results = list(src.fetch())
        assert "forge.io" in results
        assert "atlas.me" in results

    def test_skips_404_tries_next_date(self, tmp_path):
        src      = NRDSource(sources=["whoisds"])
        fail     = MagicMock()
        fail.content = b""
        fail.raise_for_status.side_effect = Exception("404")
        success  = _mock_zip_response(["forge.io"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", side_effect=[fail, success]):
                results = list(src.fetch())
        assert "forge.io" in results

    def test_skips_non_zip_tries_next_date(self, tmp_path):
        src     = NRDSource(sources=["whoisds"])
        not_zip = MagicMock()
        not_zip.content = b"not a zip"
        not_zip.raise_for_status = MagicMock()
        success = _mock_zip_response(["forge.io"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", side_effect=[not_zip, success]):
                results = list(src.fetch())
        assert "forge.io" in results

    def test_all_dates_fail_yields_nothing(self, tmp_path):
        src  = NRDSource(sources=["whoisds"])
        fail = MagicMock()
        fail.content = b""
        fail.raise_for_status.side_effect = Exception("404")
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", side_effect=[fail] * 11):
                assert list(src.fetch()) == []

    def test_saves_raw_zip(self, tmp_path):
        src = NRDSource(sources=["whoisds"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=_mock_zip_response(["forge.io"])):
                list(src.fetch())
        # one zip saved per successful date — 11 dates tried, all succeed
        assert len(list(tmp_path.glob("*whoisds*.zip"))) == 11

    def test_collects_all_successful_dates(self, tmp_path):
        src     = NRDSource(sources=["whoisds"])
        success = _mock_zip_response(["forge.io"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", return_value=success) as mock_get:
                results = list(src.fetch())
        # Should have tried all WHOISDS_LOOKBACK_DAYS + 1 dates (0..10 = 11)
        assert mock_get.call_count == 11
        assert results.count("forge.io") == 1  # deduplicated across all dates


# ------------------------------------------------------------------
# TestFetchBothSources
# ------------------------------------------------------------------

class TestFetchBothSources:
    def test_deduplicates_across_sources(self, tmp_path):
        src          = NRDSource(sources=["nrd", "whoisds"])
        github_resp  = _mock_response("forge.io\natlas.me\n")
        whoisds_resp = _mock_zip_response(["forge.io", "newdomain.com"])
        with patch("ddig.sources.nrd.DATA_DIR", tmp_path):
            with patch.object(src._session, "get", side_effect=[github_resp, whoisds_resp]):
                results = list(src.fetch())
        assert results.count("forge.io") == 1
        assert "atlas.me" in results
        assert "newdomain.com" in results


# ------------------------------------------------------------------
# TestIsAvailable
# ------------------------------------------------------------------

class TestIsAvailable:
    def test_returns_true_on_200(self):
        src       = NRDSource()
        resp      = MagicMock()
        resp.status_code = 200
        with patch.object(src._session, "head", return_value=resp):
            assert src.is_available() is True

    def test_returns_false_on_500(self):
        src       = NRDSource()
        resp      = MagicMock()
        resp.status_code = 500
        with patch.object(src._session, "head", return_value=resp):
            assert src.is_available() is False

    def test_returns_false_on_exception(self):
        src = NRDSource()
        with patch.object(src._session, "head", side_effect=Exception("timeout")):
            assert src.is_available() is False