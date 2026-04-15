"""Unit tests for the Majestic Million source."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from ddig.sources.majestic import MajesticMillionSource, _parse_int
from ddig.models.domain import Domain


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

SAMPLE_CSV = """\
GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs,IDN_Domain,IDN_TLD,PrevGlobalRank,PrevTldRank,PrevRefSubNets,PrevRefIPs
1,1,google.com,com,1000000,2000000,google.com,com,1,1,999000,1990000
2,2,youtube.com,com,900000,1800000,youtube.com,com,2,2,890000,1780000
3,3,facebook.com,com,800000,1600000,facebook.com,com,3,3,790000,1580000
4,4,twitter.com,com,700000,1400000,twitter.com,com,4,4,690000,1380000
5,1,wikipedia.org,org,600000,1200000,wikipedia.org,org,5,1,590000,1180000
6,1,atlas.app,app,500000,1000000,atlas.app,app,6,1,490000,980000
7,1,forge.io,io,400000,800000,forge.io,io,7,1,390000,780000
8,1,pixel.dev,dev,300000,600000,pixel.dev,dev,8,1,290000,580000
"""

MALFORMED_CSV = """\
GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs
1,1,,com,1000,2000
2,1,nodomain,,500,1000
3,1,valid.com,com,abc,def
4,1,good.net,net,250,500
"""

MALFORMED_FQDNS: frozenset[str] = frozenset({
    "valid.com", "good.net",
})


def _mock_streaming_response(csv_content: str, status: int = 200) -> MagicMock:
    """Return a mock requests.Response that streams lines."""
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock(
        side_effect=None if status < 400 else Exception(f"HTTP {status}")
    )
    resp.iter_lines = MagicMock(
        return_value=iter(csv_content.splitlines())
    )
    return resp


# All FQDNs present in SAMPLE_CSV — returned by mocked store
SAMPLE_FQDNS: frozenset[str] = frozenset({
    "google.com", "youtube.com", "facebook.com", "twitter.com",
    "wikipedia.org", "atlas.app", "forge.io", "pixel.dev",
})


def _make_store_mock(fqdns: frozenset[str]) -> MagicMock:
    """Return a mock DomainStore whose get_all_fqdns() returns fqdns."""
    store = MagicMock()
    store.get_all_fqdns.return_value = fqdns
    return store

def _patch_store(fqdns: frozenset[str]):
    """Context manager that patches DomainStore() to return a mock with get_all_fqdns()."""
    from unittest.mock import patch
    store_mock = _make_store_mock(fqdns)
    return patch("ddig.sources.majestic.DomainStore", return_value=store_mock)


# ------------------------------------------------------------------ #
# Init                                                                #
# ------------------------------------------------------------------ #

class TestInit:
    def test_default_url(self):
        src = MajesticMillionSource()
        assert src.url == "https://downloads.majestic.com/majestic_million.csv"

    def test_default_limit_zero(self):
        src = MajesticMillionSource()
        assert src.limit == 0

    def test_default_min_rank_zero(self):
        src = MajesticMillionSource()
        assert src.min_rank == 0

    def test_default_max_rank_zero(self):
        src = MajesticMillionSource()
        assert src.max_rank == 0

    def test_default_timeout(self):
        src = MajesticMillionSource()
        assert src.timeout == 120

    def test_custom_limit(self):
        src = MajesticMillionSource(limit=5000)
        assert src.limit == 5000

    def test_custom_min_rank(self):
        src = MajesticMillionSource(min_rank=100)
        assert src.min_rank == 100

    def test_custom_max_rank(self):
        src = MajesticMillionSource(max_rank=10000)
        assert src.max_rank == 10000

    def test_custom_url(self):
        src = MajesticMillionSource(url="https://example.com/test.csv")
        assert src.url == "https://example.com/test.csv"

    def test_session_has_user_agent(self):
        src        = MajesticMillionSource()
        user_agent = str(src._session.headers.get("User-Agent", ""))
        assert user_agent != ""
        assert "ddig" in user_agent


# ------------------------------------------------------------------ #
# is_available                                                        #
# ------------------------------------------------------------------ #

class TestIsAvailable:
    def test_always_true(self):
        src = MajesticMillionSource()
        assert src.is_available() is True

    def test_true_with_no_credentials(self):
        src = MajesticMillionSource()
        assert src.is_available() is True


# ------------------------------------------------------------------ #
# fetch() is a generator                                              #
# ------------------------------------------------------------------ #

class TestFetchIsGenerator:
    def test_fetch_is_generator_function(self):
        src = MajesticMillionSource()
        assert inspect.isgeneratorfunction(src.fetch)


# ------------------------------------------------------------------ #
# fetch() — domain parsing                                           #
# ------------------------------------------------------------------ #

class TestFetchParsesCsv:
    def test_yields_domain_objects(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert all(isinstance(d, Domain) for d in domains)

    def test_yields_correct_count(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert len(domains) == 8

    def test_domain_fqdn_correct(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        fqdns = {d.fqdn for d in domains}
        assert "google.com"    in fqdns
        assert "atlas.app"     in fqdns
        assert "wikipedia.org" in fqdns

    def test_domain_name_correct(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        names = {d.name for d in domains}
        assert "google"    in names
        assert "atlas"     in names
        assert "wikipedia" in names

    def test_fqdn_not_doubled(self):
        csv_data = (
            "GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n"
            "1,1,bit.ly,ly,5000,10000\n"
        )
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(csv_data)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(frozenset({"bit.ly"})):
            domains = list(src.fetch())
        assert domains[0].fqdn == "bit.ly"
        assert domains[0].name == "bit"
        assert domains[0].tld  == "ly"

    def test_domain_name_lowercased(self):
        csv_data = "GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n1,1,GOOGLE.COM,COM,1000,2000\n"
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(csv_data)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(frozenset({"google.com"})):
            domains = list(src.fetch())
        assert domains[0].name == "google"
        assert domains[0].tld  == "com"
        assert domains[0].fqdn == "google.com"

    def test_domain_tld_correct(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        google = next(d for d in domains if d.name == "google")
        assert google.tld == "com"

    def test_domain_source_is_majestic(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert all(d.source == "majestic" for d in domains)

    def test_backlinks_populated(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        google = next(d for d in domains if d.name == "google")
        assert google.backlinks == 1_000_000

    def test_rank_populated(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        google = next(d for d in domains if d.name == "google")
        assert google.rank == 1

    def test_rank_increments(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        ranks = [d.rank for d in domains if d.rank is not None]
        assert ranks == sorted(ranks)

    def test_fetched_at_is_timezone_aware(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert all(d.fetched_at.tzinfo is not None for d in domains)


# ------------------------------------------------------------------ #
# fetch() — malformed rows                                           #
# ------------------------------------------------------------------ #

class TestFetchHandlesMalformedRows:
    def test_skips_empty_domain(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(MALFORMED_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(MALFORMED_FQDNS):
            domains = list(src.fetch())
        fqdns = {d.fqdn for d in domains}
        assert ".com" not in fqdns

    def test_skips_empty_tld(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(MALFORMED_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(MALFORMED_FQDNS):
            domains = list(src.fetch())
        names = {d.name for d in domains}
        assert "nodomain" not in names

    def test_invalid_ref_subnets_defaults_to_zero(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(MALFORMED_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(MALFORMED_FQDNS):
            domains = list(src.fetch())
        valid = next(d for d in domains if d.name == "valid")
        assert valid.backlinks is None   # _parse_int("abc") == 0 → stored as None

    def test_valid_rows_still_yielded(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(MALFORMED_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(MALFORMED_FQDNS):
            domains = list(src.fetch())
        names = {d.name for d in domains}
        assert "valid" in names
        assert "good"  in names

    def test_empty_csv_yields_nothing(self):
        csv_data = "GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs\n"
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(csv_data)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(frozenset()):
            domains = list(src.fetch())
        assert domains == []


# ------------------------------------------------------------------ #
# fetch() — limit                                                     #
# ------------------------------------------------------------------ #

class TestFetchLimit:
    def test_limit_stops_at_n(self):
        src  = MajesticMillionSource(limit=3)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert len(domains) == 3

    def test_limit_zero_returns_all(self):
        src  = MajesticMillionSource(limit=0)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert len(domains) == 8

    def test_limit_larger_than_data_returns_all(self):
        src  = MajesticMillionSource(limit=10000)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert len(domains) == 8


# ------------------------------------------------------------------ #
# fetch() — rank filters                                              #
# ------------------------------------------------------------------ #

class TestFetchRankFilters:
    def test_max_rank_filters_lower_ranked(self):
        src  = MajesticMillionSource(max_rank=3)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert all(d.rank is not None and d.rank <= 3 for d in domains)
        assert len(domains) == 3

    def test_min_rank_filters_higher_ranked(self):
        src  = MajesticMillionSource(min_rank=5)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert all(d.rank is not None and d.rank >= 5 for d in domains)
        assert len(domains) == 4

    def test_min_and_max_rank_combined(self):
        src  = MajesticMillionSource(min_rank=3, max_rank=6)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert all(d.rank is not None and 3 <= d.rank <= 6 for d in domains)
        assert len(domains) == 4

    def test_min_rank_zero_no_lower_bound(self):
        src  = MajesticMillionSource(min_rank=0)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert len(domains) == 8

    def test_max_rank_zero_no_upper_bound(self):
        src  = MajesticMillionSource(max_rank=0)
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(SAMPLE_FQDNS):
            domains = list(src.fetch())
        assert len(domains) == 8


# ------------------------------------------------------------------ #
# fetch() — HTTP errors                                               #
# ------------------------------------------------------------------ #

class TestFetchHttpErrors:
    def test_http_error_raises(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response("", status=403)
        with patch.object(src._session, "get", return_value=resp), \
             _patch_store(frozenset()):
            with pytest.raises(Exception):
                list(src.fetch())

    def test_get_called_with_correct_url(self):
        src  = MajesticMillionSource()
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp) as mock_get, \
             _patch_store(SAMPLE_FQDNS):
            list(src.fetch())
        mock_get.assert_called_once_with(
            "https://downloads.majestic.com/majestic_million.csv",
            timeout=120,
            stream=True,
        )

    def test_get_called_with_custom_url(self):
        src  = MajesticMillionSource(url="https://example.com/custom.csv")
        resp = _mock_streaming_response(SAMPLE_CSV)
        with patch.object(src._session, "get", return_value=resp) as mock_get, \
             _patch_store(SAMPLE_FQDNS):
            list(src.fetch())
        call_url = mock_get.call_args[0][0]
        assert call_url == "https://example.com/custom.csv"


# ------------------------------------------------------------------ #
# _parse_int                                                          #
# ------------------------------------------------------------------ #

class TestParseInt:
    def test_plain_integer(self):
        assert _parse_int("42") == 42

    def test_integer_with_commas(self):
        assert _parse_int("1,000,000") == 1_000_000

    def test_zero(self):
        assert _parse_int("0") == 0

    def test_none_returns_zero(self):
        assert _parse_int(None) == 0

    def test_empty_string_returns_zero(self):
        assert _parse_int("") == 0

    def test_whitespace_returns_zero(self):
        assert _parse_int("   ") == 0

    def test_non_numeric_returns_zero(self):
        assert _parse_int("abc") == 0

    def test_float_string_returns_zero(self):
        assert _parse_int("3.14") == 0

    def test_leading_trailing_whitespace(self):
        assert _parse_int("  500  ") == 500

    def test_large_number(self):
        assert _parse_int("999999999") == 999_999_999