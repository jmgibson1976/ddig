"""
ExpiredDomains.net source — Playwright headless browser scraper.

Uses the member subdomain: https://member.expireddomains.net/

Env vars:
    EXPIREDDOMAINS_USER         — your username
    EXPIREDDOMAINS_PASS         — your password
    EXPIREDDOMAINS_SESSION      — sessionid cookie value
    EXPIREDDOMAINS_COOKIE_NAME  — override cookie name (default: reme)
    EXPIREDDOMAINS_SESSION_NAME — session cookie name  (default: ExpiredDomainssessid)
    EXPIREDDOMAINS_REMEMBER_COOKIE_NAME — remember-me cookie name (default: reme)
    EXPIREDDOMAINS_REMEMBER_SESSION     — remember-me cookie value

"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator

import tldextract

from ..models.domain import Domain
from .base import DomainSource

log = logging.getLogger(__name__)

# Member subdomain — required for logged-in access
BASE_URL   = "https://www.expireddomains.net"
MEMBER_URL = "https://member.expireddomains.net"

LIST_URLS: dict[str, str] = {
    "deleted":    "/domains/combinedexpired/",
    "expired":    "/domains/expireddomains/",
    "expiring":   "/domains/expiringdomains/",
    "registered": "/domains/newlyregistered/",
}

# Login-wall text — if this appears on page we are not logged in
LOGIN_WALL_TEXT = "Login to see all Domains"

# Column indices in the results table (0-based)
COL_DOMAIN    = 0
COL_BACKLINKS = 3
COL_TF        = 6
COL_CF        = 7
COL_AGE       = 11
COL_DROP_DATE = 14

PAGE_TIMEOUT = 60_000
NAV_TIMEOUT  = 90_000


class ExpiredDomainsSource(DomainSource):
    """
    Scrapes ExpiredDomains.net using Playwright headless Chromium.

    Requires login via remember-me cookie (reme) or username/password.
    Results are fetched from member.expireddomains.net.

    Usage::

        source = ExpiredDomainsSource(list_name="deleted", max_pages=5)
        for domain in source.fetch():
            print(domain.fqdn, domain.backlinks)
    """

    name = "expireddomains"

    def __init__(
        self,
        list_name:       str        = "deleted",
        tld:             str | None = None,
        max_pages:       int        = 10,
        headless:        bool       = True,
        slow_mo:         int        = 250,
        timeout:         int        = 30,
        username:        str | None = None,
        password:        str | None = None,
        session_cookie:  str | None = None,
        session_name:    str | None = None,
        remember_cookie: str | None = None,
        remember_name:   str | None = None,
    ) -> None:
        if list_name not in LIST_URLS:
            raise ValueError(
                f"Unknown list {list_name!r}. "
                f"Available: {list(LIST_URLS)}"
            )
        self.list_name       = list_name
        self.tld             = tld.lstrip(".").lower() if tld else None
        self.max_pages       = max_pages
        self.headless        = headless
        self.slow_mo         = slow_mo
        self.timeout         = timeout
        self.username        = username        or os.environ.get("EXPIREDDOMAINS_USER",                 "")
        self.password        = password        or os.environ.get("EXPIREDDOMAINS_PASS",                 "")
        self.session_cookie  = session_cookie  or os.environ.get("EXPIREDDOMAINS_SESSION",              "")
        self.session_name    = session_name    or os.environ.get("EXPIREDDOMAINS_SESSION_NAME",         "ExpiredDomainssessid")
        self.remember_cookie = remember_cookie or os.environ.get("EXPIREDDOMAINS_REMEMBER_SESSION",     "")
        self.remember_name   = remember_name   or os.environ.get("EXPIREDDOMAINS_REMEMBER_COOKIE_NAME", "reme")

    # ------------------------------------------------------------------ #
    # Availability                                                         #
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        try:
            import urllib.request
            urllib.request.urlopen(BASE_URL, timeout=5)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Playwright helpers                                                   #
    # ------------------------------------------------------------------ #

    def _check_playwright(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "Playwright is required for the expireddomains source.\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

    def _is_logged_in(self, page) -> bool:
        """Return True if the page does NOT show the login wall."""
        try:
            content = page.content()
            return LOGIN_WALL_TEXT not in content
        except Exception:
            return False

    def _login(self, page) -> None:
        if not self.session_cookie and not self.remember_cookie:
            # fall through to username/password
            pass
        else:
            log.info(
                "Injecting cookies — session: %r (%d chars)  remember: %r (%d chars)",
                self.session_name,    len(self.session_cookie),
                self.remember_name,   len(self.remember_cookie),
            )

            # Must visit domain first to establish context
            page.goto(BASE_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")

            cookies_to_set = []

            if self.session_cookie:
                cookies_to_set.append({
                    "name":     self.session_name,
                    "value":    self.session_cookie,
                    "domain":   ".expireddomains.net",
                    "path":     "/",
                    "httpOnly": True,
                    "secure":   True,
                    "sameSite": "Lax",
                })

            if self.remember_cookie:
                cookies_to_set.append({
                    "name":     self.remember_name,
                    "value":    self.remember_cookie,
                    "domain":   ".expireddomains.net",
                    "path":     "/",
                    "httpOnly": True,
                    "secure":   True,
                    "sameSite": "Lax",
                })

            page.context.add_cookies(cookies_to_set)
            log.debug("Set %d cookies — navigating to member subdomain…", len(cookies_to_set))

            # Navigate to member subdomain with cookies set
            page.goto(MEMBER_URL, timeout=NAV_TIMEOUT, wait_until="networkidle")

            if not self._is_logged_in(page):
                log.debug("Page content snippet: %s", page.content()[:500])
                raise RuntimeError(
                    "Cookies were rejected by member.expireddomains.net.\n"
                    "Both cookies may have expired — get fresh ones:\n"
                    "  1. Log in at https://www.expireddomains.net/login/\n"
                    "  2. DevTools → Application → Cookies → expireddomains.net\n"
                    f"  3. Copy '{self.session_name}' → EXPIREDDOMAINS_SESSION in .env\n"
                    f"  4. Copy '{self.remember_name}' → EXPIREDDOMAINS_REMEMBER_SESSION in .env"
                )

            log.info("Cookies accepted — logged in to member.expireddomains.net")
            return

        # ── Username / password fallback ──────────────────────────────
        if not self.username or not self.password:
            raise RuntimeError(
                "ExpiredDomains credentials required.\n"
                "  Set in .env:\n"
                "    EXPIREDDOMAINS_USER=yourusername\n"
                "    EXPIREDDOMAINS_PASS=yourpassword\n"
                "  Or set both cookies:\n"
                "    EXPIREDDOMAINS_SESSION=<ExpiredDomainssessid value>\n"
                "    EXPIREDDOMAINS_REMEMBER_SESSION=<reme value>"
            )

        log.info("Logging in as %s…", self.username)
        page.goto(f"{BASE_URL}/login/", timeout=NAV_TIMEOUT)
        page.wait_for_load_state("networkidle")

        page.click("#inputLogin")
        page.wait_for_timeout(300)
        page.type("#inputLogin",    self.username, delay=80)
        page.click("#inputPassword")
        page.wait_for_timeout(200)
        page.type("#inputPassword", self.password, delay=80)
        page.wait_for_timeout(400)
        page.click('form[action="/logincheck/"] input[type="submit"]')
        page.wait_for_load_state("networkidle")

        page.goto(MEMBER_URL, timeout=NAV_TIMEOUT, wait_until="networkidle")

        if not self._is_logged_in(page):
            raise RuntimeError(
                "Login failed — check EXPIREDDOMAINS_USER / EXPIREDDOMAINS_PASS."
            )

        # Capture both cookies for next time
        cookies = page.context.cookies()
        for c in cookies:
            if c["name"] in (self.session_name, self.remember_name):
                log.info("💡 Add to .env: %s=%s",
                    "EXPIREDDOMAINS_SESSION"         if c["name"] == self.session_name else "EXPIREDDOMAINS_REMEMBER_SESSION",
                    c["value"],
                )

        log.info("Login successful.")

    def _build_list_url(self, page_num: int) -> str:
        """Build member subdomain list URL with optional TLD filter and page offset."""
        path   = LIST_URLS[self.list_name]
        params: list[str] = []

        if self.tld:
            params.append(f"ftlds[]={self.tld}")
        if page_num > 1:
            params.append(f"start={(page_num - 1) * 25}")

        query = "&".join(params)
        return f"{MEMBER_URL}{path}" + (f"?{query}" if query else "")

    def _wait_for_table(self, page) -> None:
        log.debug("Waiting for results table…")
        try:
            page.wait_for_selector(
                "#listing tbody tr td a",
                timeout=PAGE_TIMEOUT,
                state="visible",
            )
        except Exception:
            log.warning("Timed out waiting for results table — page may be empty or login wall.")

    def _parse_table(self, page) -> list[dict]:
        """Extract domain rows from the rendered #listing table."""
        rows = []

        # Bail early if login wall appeared mid-session
        if not self._is_logged_in(page):
            log.error("Login wall detected mid-scrape — session expired.")
            return rows

        try:
            table_rows = page.query_selector_all("#listing tbody tr")
        except Exception as exc:
            log.warning("Could not query table rows: %s", exc)
            return rows

        for tr in table_rows:
            tds = tr.query_selector_all("td")
            if not tds or len(tds) < COL_DOMAIN + 1:
                continue

            domain_el = tds[COL_DOMAIN].query_selector("a")
            if not domain_el:
                continue
            fqdn = domain_el.inner_text().strip().lower().rstrip(".")
            if not fqdn or " " in fqdn:
                continue

            row: dict = {"fqdn": fqdn}

            if len(tds) > COL_BACKLINKS:
                row["backlinks"] = _parse_int(tds[COL_BACKLINKS].inner_text())
            if len(tds) > COL_TF:
                row["majestic_tf"] = _parse_int(tds[COL_TF].inner_text())
            if len(tds) > COL_CF:
                row["majestic_cf"] = _parse_int(tds[COL_CF].inner_text())
            if len(tds) > COL_AGE:
                row["age_years"] = _parse_int(tds[COL_AGE].inner_text())
            if len(tds) > COL_DROP_DATE:
                row["drop_date"] = _parse_date(tds[COL_DROP_DATE].inner_text())

            rows.append(row)

        log.debug("Parsed %d rows from table.", len(rows))
        return rows

    def _has_next_page(self, page) -> bool:
        try:
            next_link = page.query_selector("a.next")
            return next_link is not None and next_link.is_visible()
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Main fetch                                                           #
    # ------------------------------------------------------------------ #

    def fetch(self) -> Iterator[Domain]:
        """Launch Playwright, log in, scrape pages, yield Domain objects."""
        self._check_playwright()

        from playwright.sync_api import sync_playwright

        total = 0
        log.info(
            "Starting ExpiredDomains scrape: list=%s tld=%s max_pages=%d headless=%s",
            self.list_name, self.tld or "all", self.max_pages, self.headless,
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
                viewport={"width": 1280, "height": 800},
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            try:
                self._login(page)

                for page_num in range(1, self.max_pages + 1):
                    url = self._build_list_url(page_num)
                    log.info("Scraping page %d/%d: %s", page_num, self.max_pages, url)

                    page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
                    self._wait_for_table(page)

                    rows = self._parse_table(page)
                    if not rows:
                        log.info("No rows on page %d — stopping.", page_num)
                        break

                    for row in rows:
                        fqdn = row["fqdn"]
                        ext  = tldextract.extract(fqdn)
                        if not ext.domain or not ext.suffix:
                            continue
                        total += 1
                        yield Domain(
                            name       = ext.domain,
                            tld        = ext.suffix,
                            fqdn       = fqdn,
                            source     = self.name,
                            fetched_at = datetime.now(timezone.utc),
                            backlinks  = row.get("backlinks"),
                            drop_date  = row.get("drop_date"),
                        )

                    if not self._has_next_page(page):
                        log.info("No next page — stopping after page %d.", page_num)
                        break

                    time.sleep(2.0)

            except Exception as exc:
                log.error("Scrape failed: %s", exc, exc_info=True)
                raise
            finally:
                browser.close()

        log.info("ExpiredDomains scrape complete — %d domains yielded.", total)


# ------------------------------------------------------------------ #
# Parsing helpers                                                     #
# ------------------------------------------------------------------ #

def _parse_int(text: str) -> int | None:
    text = text.strip().replace(",", "").replace("-", "")
    try:
        return int(text) if text and text.isdigit() else None
    except (ValueError, AttributeError):
        return None


def _parse_date(text: str) -> datetime | None:
    text = text.strip()
    if not text or text in ("-", "n/a", ""):
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    log.debug("Could not parse date %r", text)
    return None