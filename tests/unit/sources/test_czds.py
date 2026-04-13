"""Unit tests for the ICANN CZDS source."""
from __future__ import annotations

import gzip
import inspect
import io
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from ddig.sources.czds import CZDSSource
from ddig.models.domain import Domain


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _mock_response(status: int = 200, body: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text        = body
    resp.json.return_value = []
    resp.raise_for_status = MagicMock(
        side_effect=None if status < 400 else Exception(f"HTTP {status}")
    )
    return resp


def _make_zone_gz(lines: list[str]) -> bytes:
    """Return gzip-compressed zone file bytes."""
    content = "\n".join(lines).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(content)
    return buf.getvalue()


SAMPLE_ZONE_LINES = [
    "; Zone file for .app",
    "app.                   900  IN  SOA  ns1.nic.app. hostmaster.nic.app. 1 900 900 604800 900",
    "atlas.app.             3600 IN  NS   ns1.example.com.",
    "atlas.app.             3600 IN  NS   ns2.example.com.",   # duplicate — should be skipped
    "forge.app.             3600 IN  NS   ns1.example.com.",
    "pixel.app.             3600 IN  NS   ns1.example.com.",
    "123abc.app.            3600 IN  NS   ns1.example.com.",
    "; comment line",
    "",
]


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def src(tmp_path):
    return CZDSSource(
        username="test@example.com",
        password="testpass",
        cache_dir=tmp_path,
        use_cache=True,
    )


@pytest.fixture
def src_with_token(tmp_path):
    # A plausible-looking fake JWT (3 segments, >100 chars)
    fake_token = "eyJhbGciOiJSUzI1NiJ9." + "a" * 500 + ".signature"
    return CZDSSource(
        token=fake_token,
        cache_dir=tmp_path,
    )


# ------------------------------------------------------------------ #
# Init                                                                #
# ------------------------------------------------------------------ #

class TestInit:
    def test_reads_username_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CZDS_USER", "env@example.com")
        src = CZDSSource(cache_dir=tmp_path)
        assert src.username == "env@example.com"

    def test_reads_password_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CZDS_PASS", "envpass")
        src = CZDSSource(cache_dir=tmp_path)
        assert src.password == "envpass"

    def test_kwarg_overrides_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CZDS_USER", "env@example.com")
        src = CZDSSource(username="kwarg@example.com", cache_dir=tmp_path)
        assert src.username == "kwarg@example.com"

    def test_token_strips_quotes(self, tmp_path):
        fake_token = "'" + "eyJhbGci." + "a" * 200 + ".sig" + "'"
        src = CZDSSource(token=fake_token, cache_dir=tmp_path)
        assert not src.token.startswith("'")
        assert not src.token.endswith("'")

    def test_token_strips_double_quotes(self, tmp_path):
        fake_token = '"' + "eyJhbGci." + "a" * 200 + ".sig" + '"'
        src = CZDSSource(token=fake_token, cache_dir=tmp_path)
        assert not src.token.startswith('"')

    def test_tlds_strips_leading_dots(self, tmp_path):
        src = CZDSSource(tlds=[".app", ".dev", "io"], cache_dir=tmp_path)
        assert src.tlds == ["app", "dev", "io"]

    def test_cache_dir_created(self, tmp_path):
        cache = tmp_path / "new_cache"
        CZDSSource(cache_dir=cache)
        assert cache.exists()

    def test_download_urls_initialised_empty(self, tmp_path):
        src = CZDSSource(cache_dir=tmp_path)
        assert src._download_urls == {}

    def test_jwt_initialised_none(self, tmp_path):
        src = CZDSSource(cache_dir=tmp_path)
        assert src._jwt is None


# ------------------------------------------------------------------ #
# fetch() is a generator                                              #
# ------------------------------------------------------------------ #

class TestFetchIsGenerator:
    def test_fetch_is_generator_function(self, src):
        assert inspect.isgeneratorfunction(src.fetch)


# ------------------------------------------------------------------ #
# Cache helpers                                                       #
# ------------------------------------------------------------------ #

class TestCacheHelpers:
    def test_cache_path_contains_tld(self, src):
        path = src._cache_path("app")
        assert "app" in path.name

    def test_cache_path_contains_today(self, src):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path  = src._cache_path("app")
        assert today in path.name

    def test_cache_path_is_in_cache_dir(self, src):
        path = src._cache_path("app")
        assert path.parent == src.cache_dir

    def test_not_cached_when_file_missing(self, src):
        assert src._is_cached("app") is False

    def test_cached_when_file_exists(self, src):
        src._cache_path("app").touch()
        assert src._is_cached("app") is True

    def test_not_cached_when_use_cache_false(self, tmp_path):
        src = CZDSSource(cache_dir=tmp_path, use_cache=False)
        src._cache_path("app").touch()
        assert src._is_cached("app") is False


# ------------------------------------------------------------------ #
# Authentication                                                      #
# ------------------------------------------------------------------ #

class TestAuthenticate:
    def test_truncated_token_raises(self, tmp_path):
        src = CZDSSource(token="eyJ\u2026truncated", cache_dir=tmp_path)
        with pytest.raises(RuntimeError, match="truncated"):
            src._authenticate()

    def test_short_token_raises(self, tmp_path):
        src = CZDSSource(token="short", cache_dir=tmp_path)
        with pytest.raises(RuntimeError, match="too short"):
            src._authenticate()

    def test_non_jwt_token_raises(self, tmp_path):
        src = CZDSSource(token="a" * 200, cache_dir=tmp_path)   # no dots
        with pytest.raises(RuntimeError, match="not a valid JWT"):
            src._authenticate()

    def test_valid_token_sets_auth_header(self, src_with_token):
        fake_resp = _mock_response(200, '["https://czds-download-api.icann.org/czds/downloads/app.zone"]')
        fake_resp.json.return_value = ["https://czds-download-api.icann.org/czds/downloads/app.zone"]
        with patch.object(src_with_token._session, "get", return_value=fake_resp):
            src_with_token._authenticate()
        assert "Authorization" in src_with_token._session.headers
        assert src_with_token._session.headers["Authorization"].startswith("Bearer ")

    def test_cached_jwt_returned_immediately(self, src_with_token):
        src_with_token._jwt = "cached-token"
        result = src_with_token._authenticate()
        assert result == "cached-token"

    def test_missing_credentials_raises(self, tmp_path):
        # No token, no user, no pass — but _authenticate() first tries the probe
        # which will fail with a network error, so we need to ensure the no-credentials
        # path is reached. Use a source with empty token that passes length check bypass.
        src = CZDSSource(cache_dir=tmp_path)
        src.token    = ""
        src._jwt     = None
        src.username = ""
        src.password = ""
        with pytest.raises(RuntimeError, match="credentials required"):
            src._authenticate()

    def test_expired_token_clears_jwt_and_falls_through(self, src_with_token):
        expired_resp = _mock_response(401)
        with patch.object(src_with_token._session, "get", return_value=expired_resp):
            with patch.object(src_with_token, "_playwright_auth", return_value="new-token") as mock_auth:
                with patch.object(src_with_token, "_save_token_to_env"):
                    # Need username/password for the fallthrough path
                    src_with_token.username = "test@example.com"
                    src_with_token.password = "testpass"
                    src_with_token._authenticate()
        mock_auth.assert_called_once()


# ------------------------------------------------------------------ #
# _get_approved_tlds                                                  #
# ------------------------------------------------------------------ #

class TestGetApprovedTlds:
    LINKS = [
        "https://czds-download-api.icann.org/czds/downloads/app.zone",
        "https://czds-download-api.icann.org/czds/downloads/dev.zone",
        "https://czds-download-api.icann.org/czds/downloads/io.zone",
    ]

    @pytest.fixture(autouse=True)
    def _pre_authenticated(self, src_with_token):
        """Pre-authenticate so _jwt is set and _authenticate() returns early."""
        probe = _mock_response(200, body="[]")       # non-empty body so text.strip() passes
        probe.json.return_value = []
        with patch.object(src_with_token._session, "get", return_value=probe):
            src_with_token._authenticate()
        # _jwt is now set — subsequent _authenticate() calls return immediately

    def _links_resp(self):
        """Return a mock response carrying the LINKS list."""
        resp = _mock_response(200, body='["placeholder"]')   # non-empty body
        resp.json.return_value = self.LINKS
        return resp

    def test_returns_tld_list(self, src_with_token):
        with patch.object(src_with_token._session, "get", return_value=self._links_resp()):
            tlds = src_with_token._get_approved_tlds()
        assert set(tlds) == {"app", "dev", "io"}

    def test_populates_download_urls(self, src_with_token):
        with patch.object(src_with_token._session, "get", return_value=self._links_resp()):
            src_with_token._get_approved_tlds()
        assert src_with_token._download_urls["app"] == self.LINKS[0]
        assert src_with_token._download_urls["dev"] == self.LINKS[1]

    def test_empty_response_returns_empty_list(self, src_with_token):
        resp = _mock_response(200, body="[]")
        resp.json.return_value = []
        with patch.object(src_with_token._session, "get", return_value=resp):
            tlds = src_with_token._get_approved_tlds()
        assert tlds == []

    def test_401_triggers_reauth(self, src_with_token):
        src_with_token.username = "test@example.com"
        src_with_token.password = "testpass"

        resp_401 = _mock_response(401, body="")
        resp_ok  = self._links_resp()

        with patch.object(src_with_token._session, "get", side_effect=[resp_401, resp_ok]):
            with patch.object(src_with_token, "_playwright_auth", return_value=src_with_token.token):
                with patch.object(src_with_token, "_save_token_to_env"):
                    # Clear _jwt so re-auth path is exercised
                    src_with_token._jwt = None
                    tlds = src_with_token._get_approved_tlds()
        assert set(tlds) == {"app", "dev", "io"}


# ------------------------------------------------------------------ #
# _download_zone                                                      #
# ------------------------------------------------------------------ #

class TestDownloadZone:
    def test_returns_cached_path_if_exists(self, src_with_token, tmp_path):
        cached = src_with_token._cache_path("app")
        cached.write_bytes(b"fake")
        result = src_with_token._download_zone("app")
        assert result == cached

    def test_returns_none_on_404(self, src_with_token):
        resp = _mock_response(404)
        with patch.object(src_with_token._session, "get", return_value=resp):
            result = src_with_token._download_zone("app")
        assert result is None

    def test_uses_download_url_from_links(self, src_with_token, tmp_path):
        src_with_token._download_urls["app"] = "https://czds-download-api.icann.org/czds/downloads/app.zone"
        gz_bytes = _make_zone_gz(SAMPLE_ZONE_LINES)
        resp = _mock_response(200)
        resp.iter_content = MagicMock(return_value=[gz_bytes])
        with patch.object(src_with_token._session, "get", return_value=resp):
            path = src_with_token._download_zone("app")
        assert path is not None
        assert path.exists()

    def test_falls_back_to_standard_url(self, src_with_token, tmp_path):
        # No entry in _download_urls — should use fallback URL pattern
        gz_bytes = _make_zone_gz(SAMPLE_ZONE_LINES)
        resp     = _mock_response(200)
        resp.iter_content = MagicMock(return_value=[gz_bytes])
        with patch.object(src_with_token._session, "get", return_value=resp) as mock_get:
            src_with_token._download_zone("app")
        call_url = mock_get.call_args[0][0]
        assert "app.zone" in call_url


# ------------------------------------------------------------------ #
# _parse_zone                                                         #
# ------------------------------------------------------------------ #

class TestParseZone:
    def test_yields_domain_objects(self, src, tmp_path):
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(SAMPLE_ZONE_LINES))
        domains = list(src._parse_zone("app", gz_path))
        assert all(isinstance(d, Domain) for d in domains)

    def test_deduplicates_domains(self, src, tmp_path):
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(SAMPLE_ZONE_LINES))
        domains = list(src._parse_zone("app", gz_path))
        fqdns   = [d.fqdn for d in domains]
        assert len(fqdns) == len(set(fqdns))

    def test_skips_comments(self, src, tmp_path):
        lines   = ["; this is a comment", "atlas.app. 3600 IN NS ns1.example.com."]
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(lines))
        domains = list(src._parse_zone("app", gz_path))
        assert len(domains) == 1

    def test_skips_zone_apex(self, src, tmp_path):
        lines   = ["app. 3600 IN SOA ns1.nic.app. hostmaster.nic.app. 1 900 900 604800 900"]
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(lines))
        domains = list(src._parse_zone("app", gz_path))
        assert len(domains) == 0

    def test_domain_source_is_czds(self, src, tmp_path):
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(SAMPLE_ZONE_LINES))
        domains = list(src._parse_zone("app", gz_path))
        assert all(d.source == "czds" for d in domains)

    def test_domain_tld_is_correct(self, src, tmp_path):
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(SAMPLE_ZONE_LINES))
        domains = list(src._parse_zone("app", gz_path))
        assert all(d.tld == "app" for d in domains)

    def test_handles_plain_text_zone(self, src, tmp_path):
        """Zone files that are plain text (not gzipped) should still parse."""
        plain_path = tmp_path / "app_plain.zone.gz"
        plain_path.write_text("\n".join(SAMPLE_ZONE_LINES))
        domains = list(src._parse_zone("app", plain_path))
        assert len(domains) > 0

    def test_expected_domains_present(self, src, tmp_path):
        gz_path = tmp_path / "app_test.zone.gz"
        gz_path.write_bytes(_make_zone_gz(SAMPLE_ZONE_LINES))
        fqdns = {d.fqdn for d in src._parse_zone("app", gz_path)}
        assert "atlas.app" in fqdns
        assert "forge.app" in fqdns
        assert "pixel.app" in fqdns


# ------------------------------------------------------------------ #
# fetch() with max_tlds                                               #
# ------------------------------------------------------------------ #

class TestFetchMaxTlds:
    LINKS = [
        "https://czds-download-api.icann.org/czds/downloads/app.zone",
        "https://czds-download-api.icann.org/czds/downloads/dev.zone",
        "https://czds-download-api.icann.org/czds/downloads/io.zone",
    ]

    def test_max_tlds_limits_processing(self, tmp_path):
        fake_token = "eyJhbGci." + "a" * 500 + ".sig"
        src        = CZDSSource(token=fake_token, cache_dir=tmp_path, max_tlds=1)

        probe_resp = _mock_response(200)
        probe_resp.json.return_value = self.LINKS

        gz_bytes  = _make_zone_gz(SAMPLE_ZONE_LINES)
        zone_resp = _mock_response(200)
        zone_resp.iter_content = MagicMock(return_value=[gz_bytes])

        with patch.object(src._session, "get", side_effect=[probe_resp, probe_resp, zone_resp]):
            domains = list(src.fetch())

        # Only 1 TLD processed — domains from that one zone file only
        assert all(d.tld == "app" for d in domains)

    def test_specific_tlds_skips_discovery(self, tmp_path):
        fake_token = "eyJhbGci." + "a" * 500 + ".sig"
        src        = CZDSSource(tlds=["app"], token=fake_token, cache_dir=tmp_path)

        probe_resp = _mock_response(200)
        probe_resp.json.return_value = self.LINKS

        gz_bytes  = _make_zone_gz(SAMPLE_ZONE_LINES)
        zone_resp = _mock_response(200)
        zone_resp.iter_content = MagicMock(return_value=[gz_bytes])

        discover_called = []

        original_get_approved = src._get_approved_tlds
        def mock_get_approved():
            discover_called.append(True)
            return original_get_approved()

        with patch.object(src, "_get_approved_tlds", side_effect=mock_get_approved):
            with patch.object(src._session, "get", side_effect=[probe_resp, zone_resp]):
                list(src.fetch())

        assert not discover_called, "_get_approved_tlds should not be called when tlds= is specified"