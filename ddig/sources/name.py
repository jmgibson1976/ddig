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
from rich.console import Console

from ddig.models.domain import Domain
from ddig.sources.base import DomainSource
from ddig.env import get_env, reload_env

log     = logging.getLogger(__name__)
console = Console()

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
        return DATA_DIR / f"name_{today}.csv"

    def _get_cookies(self) -> dict[str, str]:
        session_name    = get_env("NAME_SESSION_NAME",    "REG_IDT")
        session_value   = get_env("NAME_SESSION",         "")
        login_time_name = get_env("NAME_LOGIN_TIME_NAME", "acct_login_time")
        login_time      = get_env("NAME_LOGIN_TIME",      "")
        return {
            session_name:    session_value,
            login_time_name: login_time,
        }

    def _download(self, cookies: dict[str, str]) -> Path:
        """Download the CSV with the given cookies.  Re-authenticates via Playwright on failure."""
        log.debug("name.com: downloading %s", DOWNLOAD_URL)
        session = requests.Session()
        resp    = session.get(DOWNLOAD_URL, cookies=cookies, allow_redirects=False, timeout=30)

        if resp.status_code in (301, 302, 303, 307, 308) or _is_login_redirect(resp):
            log.info("name.com: session expired — launching Playwright to re-authenticate")
            cookies = self._auth_with_playwright()
            resp    = session.get(DOWNLOAD_URL, cookies=cookies, allow_redirects=False, timeout=30)

        resp.raise_for_status()

        dest = self._cached_path()
        dest.write_bytes(resp.content)
        log.debug("name.com: saved to %s (%d bytes)", dest, len(resp.content))

        if resp.status_code == 200 and len(resp.content) == 0:
            dest.unlink()
            raise RuntimeError("name.com: downloaded file is empty — authentication may have failed")

        return dest

    def _auth_with_playwright(self) -> dict[str, str]:
        """Headless Playwright login — handles device verification and MFA."""
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        reload_env()  # force fresh read after any _update_env calls
        username = get_env("NAME_USER")
        password = get_env("NAME_PASS")
        log.debug("name.com: auth as %s (pass len=%d)", username, len(password))

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx     = browser.new_context()
            page    = ctx.new_page()

            # ── Login ────────────────────────────────────────────────
            log.debug("name.com: navigating to %s", LOGIN_URL)
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_selector("#Login-new-form", timeout=10000)

            page.locator("#Login-new-form #acct_name").fill(username)
            log.debug("name.com: filled username")

            page.locator("#Login-new-form #password").fill(password)
            log.debug("name.com: filled password")

            page.locator("#Login-new-form #login-btn").click()
            log.debug("name.com: clicked login button")

            try:
                page.wait_for_selector("#Login-new-form", state="detached", timeout=15000)
                log.debug("name.com: login form gone — proceeding")
            except PWTimeout:
                log.warning("name.com: login form still present — check credentials")

            # ── Step 1: Unrecognized device ──────────────────────────
            try:
                page.wait_for_selector("button:has-text('Send me the code')", timeout=8000)
                try:
                    page.locator("button:has-text('Reject All')").click(timeout=3000)
                    log.debug("name.com: dismissed cookie banner")
                except PWTimeout:
                    pass
                page.locator("button:has-text('Send me the code')").click()
                log.debug("name.com: requested email code")
            except PWTimeout:
                log.debug("name.com: no unrecognized-device page")

            # ── Step 2: Security code ────────────────────────────────
            try:
                page.wait_for_selector("input[name='code']", timeout=20000)
                console.print("\n[yellow]name.com sent a security code to your email.[/yellow]")
                code = input("Enter the security code: ").strip()
                page.locator("input[name='code']").fill(code)
                page.locator("button:has-text('Verify Code')").click()
                log.debug("name.com: submitted security code")
            except PWTimeout:
                log.debug("name.com: no security code page")

            # ── Step 3: Remember this device ─────────────────────────
            try:
                page.wait_for_selector("text=Remember this device?", timeout=10000)
                page.locator("label:has-text('No, do not remember')").click()
                page.locator("button:has-text('Save and continue')").click()
                log.debug("name.com: chose not to remember device")
            except PWTimeout:
                log.debug("name.com: no remember-device page")

            # ── Capture cookies ──────────────────────────────────────
            page.wait_for_load_state("domcontentloaded")
            raw     = ctx.cookies()
            cookies = {c["name"]: c["value"] for c in raw}  # type: ignore[index]
            for name_, value_ in cookies.items():
                log.debug("name.com captured cookie: %s = %s…", name_, str(value_)[:20])
            browser.close()

        _update_env("NAME_SESSION",    cookies.get("REG_IDT",         ""))
        _update_env("NAME_LOGIN_TIME", cookies.get("acct_login_time", ""))
        return cookies

    def _parse(self, path: Path) -> Iterator[Domain]:
        """Parse a name.com CSV file and yield Domain objects."""
        content = path.read_text(encoding="utf-8")
        reader  = csv.DictReader(io.StringIO(content), delimiter=",")
        log.debug("name.com: CSV headers = %s", reader.fieldnames)
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
    content_type = resp.headers.get("content-type", "")
    if "text/csv" in content_type or "text/plain" in content_type:
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