"""
name.com source — expiring domains CSV download.

Downloads the expiring domains list from name.com using session cookies.
If cookies are missing or expired, falls back to Playwright headless login.
MFA (if prompted) requires manual terminal input.

Credentials (all required):
    NAME_USER              login email / username
    NAME_PASS              login password
    NAME_SESSION_NAME      session cookie name  (PREG_IDT)
    NAME_SESSION           session cookie value
    NAME_LOGIN_TIME_NAME   login-time cookie name  (acct_login_time)
    NAME_LOGIN_TIME        login-time cookie value
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests

from ddig.models.domain import Domain
from ddig.sources.base import DomainSource

log = logging.getLogger(__name__)

DOWNLOAD_URL = "https://www.name.com/api/expired/get_expired_domains_csv"
LOGIN_URL    = "https://www.name.com/account/login"
BASE_URL     = "https://www.name.com"
DATA_DIR     = Path("data")


class NameSource(DomainSource):
    """name.com expiring-domains source."""

    def __init__(
        self,
        headless: bool = True,
        verbose: bool = False,
    ) -> None:
        self.headless = headless
        self.verbose  = verbose
        DATA_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # DomainSource interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Returns True if session credentials are present in the environment."""
        return bool(os.environ.get("NAME_SESSION"))

    def fetch(self) -> Iterator[Domain]:
        """Authenticate (if needed), download the TSV, parse and yield Domain objects."""
        cached = self._cached_path()
        if cached.exists():
            log.debug("name.com: using cached file %s", cached)
            yield from self._parse(cached)
            return

        cookies = self._get_cookies()
        path    = self._download(cookies)
        yield from self._parse(path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cached_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return DATA_DIR / f"name_{today}.tsv"

    def _get_cookies(self) -> dict[str, str]:
        session_name    = os.environ.get("NAME_SESSION_NAME", "PREG_IDT")
        session_value   = os.environ.get("NAME_SESSION", "")
        login_time_name = os.environ.get("NAME_LOGIN_TIME_NAME", "acct_login_time")
        login_time      = os.environ.get("NAME_LOGIN_TIME", "")
        return {
            session_name:    session_value,
            login_time_name: login_time,
        }

    def _download(self, cookies: dict[str, str]) -> Path:
        """Download the TSV with the given cookies.  Re-authenticates via Playwright on failure."""
        log.debug("name.com: downloading %s", DOWNLOAD_URL)
        resp = requests.get(DOWNLOAD_URL, cookies=cookies, allow_redirects=False, timeout=30)

        if resp.status_code in (301, 302, 303, 307, 308) or _is_login_redirect(resp):
            log.info("name.com: session expired — launching Playwright to re-authenticate")
            cookies = self._auth_with_playwright()
            resp    = requests.get(DOWNLOAD_URL, cookies=cookies, allow_redirects=False, timeout=30)

        resp.raise_for_status()

        dest = self._cached_path()
        dest.write_bytes(resp.content)
        log.debug("name.com: saved to %s (%d bytes)", dest, len(resp.content))
        return dest

    def _auth_with_playwright(self) -> dict[str, str]:
        """Headless Playwright login. Pauses for MFA code if prompted."""
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        username = os.environ.get("NAME_USER", "")
        password = os.environ.get("NAME_PASS", "")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx     = browser.new_context()
            page    = ctx.new_page()

            log.debug("name.com: navigating to %s", LOGIN_URL)
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_selector("input", timeout=10000)

            # Fill username — try selectors individually
            for sel in ("input[name='username']", "input[type='email']", "#username", "#email"):
                try:
                    page.fill(sel, username, timeout=3000)
                    log.debug("name.com: filled username with selector %s", sel)
                    break
                except PWTimeout:
                    continue

            # Fill password — try selectors individually
            for sel in ("input[name='password']", "input[type='password']", "#password"):
                try:
                    page.fill(sel, password, timeout=3000)
                    log.debug("name.com: filled password with selector %s", sel)
                    break
                except PWTimeout:
                    continue

            # Submit
            for sel in ("button[type='submit']", "input[type='submit']", "button.btn-primary"):
                try:
                    page.click(sel, timeout=3000)
                    break
                except PWTimeout:
                    continue

            # after submit click:
            page.wait_for_load_state("domcontentloaded")

            # MFA — pause for manual input if we see an OTP field
            for sel in ("input[name='otp']", "input[name='code']", "#otp"):
                try:
                    page.wait_for_selector(sel, timeout=3000)
                    code = input("name.com MFA code: ").strip()
                    page.fill(sel, code, timeout=5000)
                    for submit in ("button[type='submit']", "input[type='submit']"):
                        try:
                            page.click(submit, timeout=3000)
                            break
                        except PWTimeout:
                            continue
                    page.wait_for_load_state("networkidle")
                    break
                except PWTimeout:
                    continue

            # Capture cookies
            raw     = ctx.cookies([BASE_URL])
            cookies = {c["name"]: c["value"] for c in raw}  # type: ignore[index]
            browser.close()

        # Persist updated cookies to .env
        _update_env("NAME_SESSION",    cookies.get(os.environ.get("NAME_SESSION_NAME",    "PREG_IDT"),          ""))
        _update_env("NAME_LOGIN_TIME", cookies.get(os.environ.get("NAME_LOGIN_TIME_NAME", "acct_login_time"),   ""))
        return cookies

    def _parse(self, path: Path) -> Iterator[Domain]:
        """Parse a name.com TSV file and yield Domain objects."""
        content = path.read_text(encoding="utf-8")
        reader  = csv.DictReader(io.StringIO(content), delimiter="\t")
        for row in reader:
            fqdn = row.get("domain_name", "").strip()
            if not fqdn:
                continue

            tld  = row.get("tld", "").strip()
            name = fqdn[: fqdn.rfind(".")] if "." in fqdn else fqdn

            drop_date: datetime | None = None
            raw_date = row.get("expiring_date", "").strip()
            if raw_date:
                try:
                    drop_date = datetime.fromisoformat(raw_date)
                except ValueError:
                    log.debug("name.com: could not parse date %r for %s", raw_date, fqdn)

            yield Domain(
                fqdn      = fqdn,
                name      = name,
                tld       = tld,
                source    = "name",
                drop_date = drop_date,
            )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _is_login_redirect(resp: requests.Response) -> bool:
    """Returns True if the response body looks like a login page."""
    if resp.status_code != 200:
        return False
    snippet = resp.text[:2048].lower()
    return "sign-in" in snippet or "sign in" in snippet or "login" in snippet


def _update_env(key: str, value: str) -> None:
    """Overwrite a single key in .env without touching other lines."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    lines    = env_path.read_text().splitlines(keepends=True)
    new_line = f"{key}={value}\n"
    updated  = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = new_line
            updated   = True
            break
    if not updated:
        lines.append(new_line)
    env_path.write_text("".join(lines))