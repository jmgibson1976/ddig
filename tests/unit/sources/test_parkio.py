"""Unit tests for the Park.io source."""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ddig.models.domain import Domain
from ddig.sources.parkio import ParkIOSource, ALL_TLDS


def _mock_response(domains: list[dict], next_page: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = json.dumps({
        "success":  True,
        "domains":  domains,
        "nextPage": next_page,
        "page":     1,
        "count":    len(domains),
        "limit":    200,
    })
    resp.json.return_value = json.loads(resp.text)
    resp.raise_for_status = MagicMock()
    return resp


SAMPLE_ITEMS = [
    {"id": "1", "name": "example.io",  "date_available": "2026-05-01", "date_registered": "2025-05-01", "tld": "io"},
    {"id": "2", "name": "forge.io",    "date_available": "2026-05-02", "date_registered": "",           "tld": "io"},
    {"id": "3", "name": "",            "date_available": "2026-05-01", "date_registered": "",           "tld": "io"},
]


class TestInit:
    def test_default_tlds_are_all_supported(self):
        src = ParkIOSource()
        assert src._tlds == ALL_TLDS
        assert len(src._tlds) == 18

    def test_custom_tlds_respected(self):
        src = ParkIOSource(tlds=["io", "co"])
        assert src._tlds == ["io", "co"]

    def test_default_max_pages(self):
        from ddig.sources.parkio import DEFAULT_MAX_PAGES
        src = ParkIOSource()
        assert src._max_pages == DEFAULT_MAX_PAGES

    def test_custom_max_pages(self):
        src = ParkIOSource(max_pages=50)
        assert src._max_pages == 50


class TestParseItem:
    def test_valid_item_returns_domain(self):
        src = ParkIOSource()
        item = {"name": "example.io", "date_available": "2026-05-01", "date_registered": "2025-01-01", "tld": "io"}
        domain = src._parse_item(item, "io")
        assert domain is not None
        assert domain.fqdn == "example.io"
        assert domain.name == "example"
        assert domain.tld  == "io"

    def test_drop_date_from_date_available(self):
        from datetime import datetime
        src = ParkIOSource()
        item = {"name": "example.io", "date_available": "2026-05-01", "date_registered": "", "tld": "io"}
        domain = src._parse_item(item, "io")
        assert domain is not None
        assert domain.drop_date == datetime(2026, 5, 1)

    def test_expiry_date_from_date_registered(self):
        from datetime import datetime
        src = ParkIOSource()
        item = {"name": "example.io", "date_available": "2026-05-01", "date_registered": "2025-05-01", "tld": "io"}
        domain = src._parse_item(item, "io")
        assert domain is not None
        assert domain.expiry_date == datetime(2025, 5, 1)

    def test_empty_date_registered_gives_none_expiry(self):
        src = ParkIOSource()
        item = {"name": "example.io", "date_available": "2026-05-01", "date_registered": "", "tld": "io"}
        domain = src._parse_item(item, "io")
        assert domain is not None
        assert domain.expiry_date is None

    def test_empty_fqdn_returns_none(self):
        src = ParkIOSource()
        assert src._parse_item({"name": "", "date_available": "", "tld": "io"}, "io") is None

    def test_source_field_set_to_parkio(self):
        src = ParkIOSource()
        item = {"name": "example.io", "date_available": "2026-05-01", "date_registered": "", "tld": "io"}
        domain = src._parse_item(item, "io")
        assert domain is not None
        assert domain.source == "parkio"

    def test_fqdn_matches_name_plus_tld(self):
        src = ParkIOSource()
        item = {"name": "forge.io", "date_available": "2026-05-01", "date_registered": "", "tld": "io"}
        domain = src._parse_item(item, "io")
        assert domain is not None
        assert domain.fqdn == f"{domain.name}.{domain.tld}"


class TestFetch:
    def test_is_generator(self):
        assert inspect.isgeneratorfunction(ParkIOSource.fetch)

    def test_yields_domain_objects(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS)):
            results = list(src.fetch())
        assert all(isinstance(d, Domain) for d in results)

    def test_skips_empty_fqdn_rows(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS)):
            results = list(src.fetch())
        assert all(d.fqdn for d in results)

    def test_stops_pagination_when_next_page_false(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS, next_page=False)) as mock_get:
            list(src.fetch())
        assert mock_get.call_count == 1

    def test_continues_pagination_when_next_page_true(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        page1 = _mock_response(SAMPLE_ITEMS[:1], next_page=True)
        page2 = _mock_response(SAMPLE_ITEMS[1:2], next_page=False)
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=[page1, page2]):
            results = list(src.fetch())
        assert len(results) == 2

    def test_iterates_all_tlds(self, tmp_path):
        src = ParkIOSource(tlds=["io", "co"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS[:1])) as mock_get:
            list(src.fetch())
        assert mock_get.call_count == 2

    def test_empty_response_yields_nothing(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            assert list(src.fetch()) == []

    def test_http_error_yields_nothing(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", side_effect=Exception("timeout")):
            assert list(src.fetch()) == []

    def test_success_false_yields_nothing(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"success": False, "domains": []})
        mock_resp.json.return_value = {"success": False, "domains": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            assert list(src.fetch()) == []


class TestIsAvailable:
    def test_returns_true_when_success_true(self):
        src = ParkIOSource()
        with patch.object(src._session, "get", return_value=_mock_response([])):
            assert src.is_available() is True

    def test_returns_false_on_exception(self):
        src = ParkIOSource()
        with patch.object(src._session, "get", side_effect=Exception("timeout")):
            assert src.is_available() is False

    def test_returns_false_on_empty_response(self):
        src = ParkIOSource()
        mock_resp = MagicMock()
        mock_resp.text = ""
        with patch.object(src._session, "get", return_value=mock_resp):
            assert src.is_available() is False

    def test_warns_when_page_cap_hit(self, tmp_path):
        src = ParkIOSource(tlds=["io"], max_pages=1)
        page1 = _mock_response(SAMPLE_ITEMS[:1], next_page=True)
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=page1), \
             patch("ddig.sources.parkio.log") as mock_log:
            list(src.fetch())
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("cap" in w or "more pages" in w for w in warning_calls)

    def test_no_warning_when_cap_not_hit(self, tmp_path):
        src = ParkIOSource(tlds=["io"], max_pages=10)
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS, next_page=False)), \
             patch("ddig.sources.parkio.log") as mock_log:
            list(src.fetch())
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert not any("cap" in w for w in warning_calls)


# ------------------------------------------------------------------ #
# Caching (_fetch_tld / _local_path)                                  #
# ------------------------------------------------------------------ #

class TestCaching:
    def test_data_dir_created_on_init(self, tmp_path):
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path / "parkio"):
            ParkIOSource()
            assert (tmp_path / "parkio").exists()

    def test_downloads_and_saves_when_no_cache(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS[:1])):
            list(src.fetch())
        saved = list(tmp_path.glob("parkio_io_*.json"))
        assert len(saved) == 1

    def test_uses_cached_file_skips_download(self, tmp_path):
        src   = ParkIOSource(tlds=["io"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = tmp_path / f"parkio_io_{today}.json"
        cached.write_text(json.dumps(SAMPLE_ITEMS[:1]), encoding="utf-8")
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get") as mock_get:
            list(src.fetch())
        mock_get.assert_not_called()

    def test_cached_file_yields_same_domains(self, tmp_path):
        src   = ParkIOSource(tlds=["io"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = tmp_path / f"parkio_io_{today}.json"
        cached.write_text(json.dumps(SAMPLE_ITEMS[:2]), encoding="utf-8")
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path):
            domains = list(src.fetch())
        assert len(domains) == 2

    def test_cache_filename_includes_tld_and_today(self, tmp_path):
        src   = ParkIOSource(tlds=["co"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS[:1])):
            list(src.fetch())
        saved = list(tmp_path.glob("parkio_co_*.json"))
        assert saved[0].name == f"parkio_co_{today}.json"

    def test_each_tld_cached_separately(self, tmp_path):
        src = ParkIOSource(tlds=["io", "co"])
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=_mock_response(SAMPLE_ITEMS[:1])):
            list(src.fetch())
        saved = list(tmp_path.glob("parkio_*.json"))
        assert len(saved) == 2

    def test_empty_response_does_not_save_cache(self, tmp_path):
        src = ParkIOSource(tlds=["io"])
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_resp.raise_for_status = MagicMock()
        with patch("ddig.sources.parkio.DATA_DIR", tmp_path), \
             patch.object(src._session, "get", return_value=mock_resp):
            list(src.fetch())
        saved = list(tmp_path.glob("parkio_io_*.json"))
        assert len(saved) == 0