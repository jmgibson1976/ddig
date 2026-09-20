"""
ICANN CZDS (Centralized Zone Data Service) source.

Provides access to gTLD zone files containing every registered domain
for a TLD — the most complete dataset available.

Registration (free): https://czds.icann.org/home
  - Request access to individual TLDs after registering
  - Approval typically takes 24–48 hours per TLD
  - .com/.net are NOT available (Verisign controls those)
  - Most new gTLDs are available: .app .dev .io .shop .online etc.

Auth flow:
  1. POST https://account.icann.org/api/authenticate  → JWT token
  2. GET  https://czds-api.icann.org/czds/requests     → list approved TLDs
  3. GET  https://czds-api.icann.org/czds/downloads/<tld>.zone → gzipped zone file

Env vars:
    CZDS_USER   — your ICANN account email
    CZDS_PASS   — your ICANN account password
"""
from __future__ import annotations

import gzip
import io
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests
import tldextract
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models.domain import Domain
from .base import DomainSource
from ddig.env import get_env

log = logging.getLogger(__name__)

# ICANN has TWO auth endpoints:
# 1. https://account.icann.org/api/authenticate  — Okta SSO (browser flow)
# 2. https://czds-api.icann.org/czds/authenticate — direct API auth (works for scripts)
AUTH_URL         = "https://account.icann.org/api/authenticate"
BASE_URL         = "https://czds-api.icann.org"
DOWNLOADS_URL    = f"{BASE_URL}/czds/downloads/links"
ALL_REQUESTS_URL = f"{BASE_URL}/czds/requests/all"

# Zone file line format (RFC 1035):
# <name> <ttl> <class> <type> <rdata>
# example.com. 3600 IN NS ns1.example.com.
# We only want NS or SOA records to identify registered domains
WANTED_TYPES = frozenset({"ns", "soa"})

# Cache JWT token for the session
_token_cache: dict[str, str | float] = {}


class CZDSSource(DomainSource):
    """
    Downloads gTLD zone files from ICANN CZDS and yields registered domains.

    Each zone file contains every registered domain for a TLD.
    Zone files are updated daily.

    Usage::

        source = CZDSSource(tlds=["app", "dev", "io"])
        for domain in source.fetch():
            print(domain)

    Or fetch all approved TLDs::

        source = CZDSSource()   # tlds=None → fetch all approved
        for domain in source.fetch():
            print(domain)
    """

    name = "czds"

    def __init__(
        self,
        tlds:       list[str] | None = None,
        cache_dir:  Path | str | None = None,
        timeout:    int  = 300,       # zone files can be large
        username:   str | None = None,
        password:   str | None = None,
        token:      str | None = None,
        max_tlds:   int | None = None,  # limit for testing
        use_cache:  bool = True,        # skip re-download if cached today
    ) -> None:
        self.tlds      = [t.lstrip(".").lower() for t in tlds] if tlds else None
        self.timeout   = timeout
        self.username  = username or get_env("CZDS_USER", "")
        self.password  = password or get_env("CZDS_PASS", "")
        self.token     = (token or get_env("CZDS_TOKEN", "")).strip().strip("'\"")
        self.max_tlds  = max_tlds
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir or (Path.home() / ".ddig" / "czds_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "ddig/1.0 (ICANN CZDS client)",
            "Accept":     "application/json",
        })
        self._jwt:           str | None       = None
        self._download_urls: dict[str, str]   = {}   # populated by _get_approved_tlds

    # ------------------------------------------------------------------ #
    # Auth                                                                 #
    # ------------------------------------------------------------------ #

    def _playwright_auth(self) -> str:
        """
        Use Playwright to log in to czds.icann.org via Okta and capture the JWT
        from a network response to czds-api.icann.org.
        """
        log.info("Using Playwright to authenticate with ICANN as %s…", self.username)

        from playwright.sync_api import sync_playwright

        token: str | None = None

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=200,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )

            page = context.new_page()

            def _on_request(request):
                nonlocal token
                if token:
                    return
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and "czds-api.icann.org" in request.url:
                    candidate = auth.removeprefix("Bearer ").strip()
                    if len(candidate) > 100 and candidate.count(".") >= 2:
                        log.info("✅ JWT intercepted from network request (%d chars)", len(candidate))
                        token = candidate

            page.on("request", _on_request)

            log.info("Navigating to czds.icann.org…")
            page.goto("https://czds.icann.org", timeout=60_000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")

            # ── Step 0: click the Sign In button on the home page ─────
            try:
                log.info("Looking for Sign In button…")
                sign_in_btn = (
                    page.query_selector('button.icann-btn')
                    or page.query_selector('button:has-text("Sign In")')
                )
                if sign_in_btn:
                    log.info("Clicking Sign In button…")
                    sign_in_btn.click()
                    page.wait_for_load_state("networkidle")
                else:
                    log.warning("Sign In button not found — may already be on login page.")
            except Exception as exc:
                log.warning("Sign In button step failed (%s) — continuing…", exc)

            # ── Step 1: fill email ─────────────────────────────────────
            try:
                log.info("Filling email — looking for #emailAddress…")
                page.wait_for_selector("#emailAddress", timeout=15_000)
                page.fill("#emailAddress", self.username)
                page.wait_for_timeout(400)

                next_btn = (
                    page.query_selector('input[type="submit"]')
                    or page.query_selector('button[type="submit"]')
                    or page.query_selector('button:has-text("Next")')
                )
                if next_btn:
                    next_btn.click()
                else:
                    page.keyboard.press("Enter")

                page.wait_for_load_state("networkidle")
                log.info("Email submitted — waiting for password field…")

            except Exception as exc:
                log.warning("Email step failed (%s) — may already be on password page.", exc)

            # ── Step 2: fill password ──────────────────────────────────
            try:
                log.info("Looking for password field…")
                page.wait_for_selector(
                    'input[type="password"]',
                    timeout=15_000,
                )
                page.fill('input[type="password"]', self.password)
                page.wait_for_timeout(400)

                submit = (
                    page.query_selector('input[type="submit"]')
                    or page.query_selector('button[type="submit"]')
                    or page.query_selector('button:has-text("Sign In")')
                    or page.query_selector('button:has-text("Verify")')
                )
                if submit:
                    submit.click()
                else:
                    page.keyboard.press("Enter")

                page.wait_for_load_state("networkidle")
                log.info("Password submitted.")

            except Exception as exc:
                log.warning("Password step failed (%s) — waiting for manual completion…", exc)

            # ── Step 3: wait for MFA / redirect to czds.icann.org ─────
            if "czds.icann.org" not in page.url:
                log.info(
                    "⏳ Waiting for MFA / manual login (up to 2 min)…\n"
                    "   Complete any prompts in the browser window."
                )
                try:
                    page.wait_for_url("**/czds.icann.org/**", timeout=120_000)
                    page.wait_for_load_state("networkidle")
                except Exception:
                    log.warning("Timed out waiting for czds.icann.org — proceeding anyway.")

            # ── Step 4: trigger an API call if we haven't got the token yet ──
            if not token:
                log.info("Navigating to zone-requests to trigger API call…")
                page.goto(
                    "https://czds.icann.org/zone-requests/all",
                    timeout=30_000,
                    wait_until="networkidle",
                )
                page.wait_for_timeout(3_000)

            # ── Step 5: last resort — hit the API endpoint directly ───
            if not token:
                log.info("Trying downloads/links endpoint directly…")
                page.goto(
                    "https://czds-api.icann.org/czds/downloads/links",
                    timeout=30_000,
                    wait_until="networkidle",
                )
                page.wait_for_timeout(2_000)

            browser.close()

        if not token:
            raise RuntimeError(
                "Could not capture CZDS JWT from browser session.\n"
                "Try manually:\n"
                "  1. Log in at https://czds.icann.org\n"
                "  2. DevTools → Network → any czds-api.icann.org request\n"
                "  3. Headers → Authorization: Bearer <token>\n"
                "  4. Set CZDS_TOKEN=<token> in .env"
            )

        log.info("JWT captured (%d chars).", len(token))
        return token

    def _authenticate(self) -> str:
        if self._jwt:
            return self._jwt

        if self.token:
            if "…" in self.token or "\u2026" in self.token:
                raise RuntimeError("CZDS_TOKEN appears truncated (contains '…'). Copy the full value.")
            if len(self.token) < 100:
                raise RuntimeError(f"CZDS_TOKEN too short ({len(self.token)} chars) — likely truncated.")
            if self.token.count(".") < 2:
                raise RuntimeError("CZDS_TOKEN is not a valid JWT (expected 3 dot-separated segments).")

            log.info("Using bearer token from CZDS_TOKEN (%d chars).", len(self.token))
            self._jwt = self.token
            self._session.headers["Authorization"] = f"Bearer {self.token}"

            # Probe with the correct endpoint
            try:
                probe = self._session.get(DOWNLOADS_URL, timeout=15)
                if probe.status_code == 401:
                    log.warning("CZDS_TOKEN returned 401 — token expired. Re-authenticating via Playwright…")
                    self._jwt  = None
                    self.token = ""
                    del self._session.headers["Authorization"]
                    # fall through to Playwright below
                else:
                    return self.token
            except Exception as exc:
                log.warning("CZDS token probe failed (%s) — continuing anyway.", exc)
                return self.token

        # No valid token — use Playwright
        if not self.username or not self.password:
            raise RuntimeError(
                "ICANN credentials required.\n"
                "  Set in .env:\n"
                "    CZDS_USER=your@email.com\n"
                "    CZDS_PASS=yourpassword\n"
                "  Or grab a token manually:\n"
                "    CZDS_TOKEN=<Bearer token from DevTools>"
            )

        token = self._playwright_auth()
        self._jwt = token
        self._session.headers["Authorization"] = f"Bearer {token}"
        self._save_token_to_env(token)
        return token

    def _save_token_to_env(self, token: str) -> None:
        """Write the fresh JWT back to .env so the next run uses it directly."""
        from dotenv import find_dotenv
        env_path = Path(find_dotenv(usecwd=True))
        if not env_path.exists():
            log.debug("No .env file found — skipping token persistence.")
            return

        lines     = env_path.read_text().splitlines(keepends=True)
        new_line  = f"CZDS_TOKEN={token}\n"
        replaced  = False

        for i, line in enumerate(lines):
            if line.startswith("CZDS_TOKEN="):
                lines[i] = new_line
                replaced  = True
                break

        if not replaced:
            lines.append(new_line)

        env_path.write_text("".join(lines))
        log.info("✅ Updated CZDS_TOKEN in %s", env_path)

    # ------------------------------------------------------------------ #
    # Cache helpers                                                        #
    # ------------------------------------------------------------------ #

    def _cache_path(self, tld: str) -> Path:
        """Return the path where the zone file for a TLD is cached today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.cache_dir / f"{tld}_{today}.zone.gz"

    def _is_cached(self, tld: str) -> bool:
        """Return True if a fresh zone file for this TLD is already cached today."""
        if not self.use_cache:
            return False
        return self._cache_path(tld).exists()

    # ------------------------------------------------------------------ #
    # TLD discovery                                                        #
    # ------------------------------------------------------------------ #

    def _get_approved_tlds(self) -> list[str]:
        self._authenticate()

        log.info("Fetching approved TLD download links from CZDS…")
        resp = self._session.get(DOWNLOADS_URL, timeout=30)

        log.debug("Downloads status: %s  body: %r",
                  resp.status_code, resp.text[:300])

        if resp.status_code == 401:
            # Token expired mid-session — re-auth and retry once
            log.warning("Downloads returned 401 — re-authenticating…")
            self._jwt  = None
            self.token = ""
            if "Authorization" in self._session.headers:
                del self._session.headers["Authorization"]
            self._authenticate()
            resp = self._session.get(DOWNLOADS_URL, timeout=30)
            if resp.status_code == 401:
                raise RuntimeError("CZDS API rejected token after re-auth. Run: ddig czds-auth")

        resp.raise_for_status()

        data = resp.json() if resp.text.strip() else []

        # Response is a list of download URLs — store them for use in _download_zone
        # e.g. "https://czds-download-api.icann.org/czds/downloads/app.zone"
        approved = []
        self._download_urls: dict[str, str] = {}   # tld → full download URL

        if isinstance(data, list):
            for url in data:
                tld = url.rstrip("/").split("/")[-1].replace(".zone", "").lstrip(".")
                if tld:
                    approved.append(tld.lower())
                    self._download_urls[tld.lower()] = url

        log.info("Found %d approved TLDs: %s", len(approved), approved[:20])
        return approved

    def _download_zone(self, tld: str) -> Path | None:
        cache_path = self._cache_path(tld)

        if self._is_cached(tld):
            log.info("Using cached zone file for .%s (%s)", tld, cache_path.name)
            return cache_path

        # Use the exact URL from the links response if available,
        # otherwise fall back to the standard pattern
        url = getattr(self, "_download_urls", {}).get(
            tld,
            f"https://czds-download-api.icann.org/czds/downloads/{tld}.zone"
        )
        log.info("Downloading .%s zone file from %s…", tld, url)

        t0   = time.perf_counter()
        resp = self._session.get(url, timeout=self.timeout, stream=True)

        if resp.status_code == 404:
            log.warning(".%s zone file not found (404) — skipping.", tld)
            return None
        if resp.status_code == 401:
            self._jwt = None
            self._authenticate()
            resp = self._session.get(url, timeout=self.timeout, stream=True)

        resp.raise_for_status()

        total_bytes = 0
        with cache_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                fh.write(chunk)
                total_bytes += len(chunk)

        elapsed = time.perf_counter() - t0
        log.info(
            "Downloaded .%s zone file: %.1f MB in %.1fs",
            tld, total_bytes / 1_048_576, elapsed,
        )
        return cache_path

    # ------------------------------------------------------------------ #
    # Zone file parsing                                                    #
    # ------------------------------------------------------------------ #

    def _parse_zone(self, tld: str, gz_path: Path) -> Iterator[Domain]:
        """
        Parse a gzipped zone file and yield Domain objects.

        Zone file format (each line):
            example.com.    3600    IN    NS    ns1.example.com.
            example.com.    3600    IN    NS    ns2.example.com.

        We deduplicate by name — only yield the first record per domain.
        """
        seen: set[str] = set()
        tld_dot = f".{tld}."

        log.info("Parsing .%s zone file…", tld)
        t0 = time.perf_counter()
        count = 0

        try:
            with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()

                    # Skip comments and empty lines
                    if not line or line.startswith(";"):
                        continue

                    parts = line.split()
                    if len(parts) < 4:
                        continue

                    # Only process NS records (one per domain is enough)
                    record_type = parts[3].lower() if len(parts) > 3 else ""
                    if record_type not in WANTED_TYPES:
                        continue

                    # Name field — strip trailing dot
                    raw_name = parts[0].rstrip(".")
                    if not raw_name:
                        continue

                    # Skip zone apex (just the TLD itself)
                    if raw_name.lower() == tld:
                        continue

                    fqdn = raw_name.lower()
                    if fqdn in seen:
                        continue
                    seen.add(fqdn)

                    ext = tldextract.extract(fqdn)
                    if not ext.domain or not ext.suffix:
                        continue

                    count += 1
                    yield Domain(
                        name       = ext.domain,
                        tld        = ext.suffix,
                        fqdn       = fqdn,
                        source     = self.name,
                        fetched_at = datetime.now(timezone.utc),
                    )

        except gzip.BadGzipFile:
            # Some zone files are plain text
            log.debug(".%s zone file is not gzipped — trying plain text.", tld)
            with gz_path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith(";"):
                        continue
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    record_type = parts[3].lower()
                    if record_type not in WANTED_TYPES:
                        continue
                    raw_name = parts[0].rstrip(".")
                    if not raw_name or raw_name.lower() == tld:
                        continue
                    fqdn = raw_name.lower()
                    if fqdn in seen:
                        continue
                    seen.add(fqdn)
                    ext = tldextract.extract(fqdn)
                    if not ext.domain or not ext.suffix:
                        continue
                    count += 1
                    yield Domain(
                        name       = ext.domain,
                        tld        = ext.suffix,
                        fqdn       = fqdn,
                        source     = self.name,
                        fetched_at = datetime.now(timezone.utc),
                    )

        elapsed = time.perf_counter() - t0
        log.info(
            "Parsed .%s: %d domains in %.1fs (%.0f/sec)",
            tld, count, elapsed, count / elapsed if elapsed > 0 else 0,
        )

    # ------------------------------------------------------------------ #
    # Main fetch                                                           #
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        try:
            r = requests.head(AUTH_URL, timeout=5)
            return r.status_code < 500
        except requests.RequestException:
            return False

    def fetch(self) -> Iterator[Domain]:
        """Authenticate, download zone files, and yield Domain objects."""
        self._authenticate()

        if self.tlds:
            tlds = self.tlds
        else:
            tlds = self._get_approved_tlds()

        # Fix: check explicitly for not None so max_tlds=0 doesn't silently no-op
        if self.max_tlds is not None and self.max_tlds > 0:
            tlds = tlds[: self.max_tlds]

        log.info("Processing %d TLD(s): %s", len(tlds), tlds)

        for tld in tlds:
            try:
                gz_path = self._download_zone(tld)
                if gz_path is None:
                    continue
                yield from self._parse_zone(tld, gz_path)
            except Exception as exc:
                log.error("Failed to process .%s: %s", tld, exc, exc_info=True)
                continue