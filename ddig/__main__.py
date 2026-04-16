"""
DDig CLI  — domain discovery tool.

Commands:
    fetch   Download domains from a source and save to local DB
    search  Query the local database
    score   Run NLP scoring on unscored domains
    stats   Show database statistics
    export  Export search results to CSV or JSON
"""
from __future__ import annotations

import csv
import json
import importlib.metadata
import logging
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Load .env relative to this file — works regardless of cwd
load_dotenv(Path(__file__).parent.parent / ".env")

from .sources.dropcatch import DropCatchSource, REQUEST_TYPES as DROPCATCH_FEEDS
from .sources.expireddomains import ExpiredDomainsSource, LIST_URLS as ED_LISTS
from .sources.czds import CZDSSource
from .sources.majestic import MajesticMillionSource
from .sources.name import NameSource
from .storage.datastore import DomainStore, DEFAULT_DB_PATH
from .nlp.scorer import DomainScorer

app = typer.Typer(
    name="ddig",
    help="DDig: expired & expiring domain discovery tool.",
    add_completion=False,
)
console = Console()


# ---------------------------------------------------------------------------
# helpers  (must be defined before any command functions)
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level    = logging.DEBUG if verbose else logging.INFO,
        handlers = [RichHandler(rich_tracebacks=True, show_path=False)],
        format   = "%(message)s",
        datefmt  = "[%x %X]",
    )


# ---------------------------------------------------------------------------
# watch (sub-app — registered before @app.command decorators)
# ---------------------------------------------------------------------------

watch_app = typer.Typer(help="Manage the domain watchlist.")
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(
    fqdns:   list[str] = typer.Argument(..., help="One or more FQDNs to watch"),
    db:      Path      = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool      = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Pin one or more domains to the watchlist."""
    _setup_logging(verbose)
    store = DomainStore(db_path=db)
    added = store.watch_add(fqdns)
    for fqdn in added:
        console.print(f"[green]✓[/green] Watching [bold]{fqdn}[/bold]")
    for fqdn in set(fqdns) - set(added):
        console.print(f"[dim]Already watching {fqdn}[/dim]")


@watch_app.command("remove")
def watch_remove(
    fqdns:   list[str] = typer.Argument(..., help="One or more FQDNs to remove"),
    db:      Path      = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool      = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Unpin one or more domains from the watchlist."""
    _setup_logging(verbose)
    store   = DomainStore(db_path=db)
    removed = store.watch_remove(fqdns)
    for fqdn in removed:
        console.print(f"[green]✓[/green] Removed [bold]{fqdn}[/bold]")
    for fqdn in set(fqdns) - set(removed):
        console.print(f"[yellow]Not in watchlist: {fqdn}[/yellow]")


@watch_app.command("list")
def watch_list(
    db:      Path = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show all watched domains."""
    _setup_logging(verbose)
    store   = DomainStore(db_path=db)
    entries = store.watch_list()

    if not entries:
        console.print("[yellow]Watchlist is empty.[/yellow]")
        raise typer.Exit(0)

    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("FQDN",      style="bold white", no_wrap=True)
    table.add_column("Score",     style="green",      justify="right", width=6)
    table.add_column("Backlinks", style="cyan",       justify="right", width=10)
    table.add_column("Rank",      style="dim cyan",   justify="right", width=8)
    table.add_column("Drop",      style="yellow",     width=12)
    table.add_column("Added",     style="dim",        width=12)

    for entry in entries:
        d        = entry["domain"]
        added_at = entry["added_at"][:10]
        if d:
            score     = f"{d.nlp_score:.2f}" if d.nlp_score  is not None else "—"
            backlinks = f"{d.backlinks:,}"   if d.backlinks   is not None else "—"
            rank      = f"{d.rank:,}"        if d.rank        is not None else "—"
            drop      = d.drop_date.strftime("%Y-%m-%d") if d.drop_date else "—"
        else:
            score = backlinks = rank = drop = "—"
        table.add_row(entry["fqdn"], score, backlinks, rank, drop, added_at)

    console.print(table)
    console.print(f"\n[dim]{len(entries)} watched domain(s)[/dim]")


@watch_app.command("clear")
def watch_clear(
    db:      Path = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Remove all domains from the watchlist."""
    _setup_logging(verbose)
    if not confirm:
        typer.confirm("Clear entire watchlist?", abort=True)
    store   = DomainStore(db_path=db)
    removed = store.watch_clear()
    console.print(f"[green]✓[/green] Cleared {removed:,} watched domain(s)")


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

@app.command()
def fetch(
    source:   str            = typer.Option(...,   "--source",   "-s", help="dropcatch | expireddomains | czds | majestic"),
    feed:     Optional[str]  = typer.Option(None,  "--feed",     "-f", help="dropcatch: dropping-today | all-auctions | …  expireddomains: deleted | expired | …"),
    tld:      str  = typer.Option(None,             "--tld",     "-t"),
    tlds:     str  = typer.Option(None,             "--tlds"),
    pages:    int  = typer.Option(10,               "--pages",   "-p"),
    max_tlds: int  = typer.Option(None,             "--max-tlds"),
    headless: bool = typer.Option(True,             "--headless/--no-headless",
                                   help="Playwright headless mode (expireddomains only)"),
    db:       Path = typer.Option(DEFAULT_DB_PATH,  "--db"),
    score:    bool = typer.Option(False,            "--score"),
    verbose:  bool = typer.Option(False,            "--verbose", "-v"),
    limit:   int            = typer.Option(0,     "--limit",    help="Majestic: max rows to fetch (0 = all 1M)"),
    min_rank: int           = typer.Option(0,     "--min-rank", help="Majestic: skip domains ranked below this"),
    max_rank: int           = typer.Option(0,     "--max-rank", help="Majestic: skip domains ranked above this"),
) -> None:
    """Download domains from a source and store them locally."""
    import time
    _setup_logging(verbose)

    store = DomainStore(db_path=db)

    if source == "dropcatch":
        resolved_feed = feed or "dropping-today"
        src = DropCatchSource(feed=resolved_feed)

    elif source == "expireddomains":
        resolved_feed = feed or "deleted"
        src = ExpiredDomainsSource(
            list_name = resolved_feed,
            tld       = tld,
            max_pages = pages,
            headless  = headless,
        )

    elif source == "czds":
        tld_list = [t.strip() for t in tlds.split(",")] if tlds else None
        src = CZDSSource(tlds=tld_list, max_tlds=max_tlds)

    elif source == "majestic":
        # feed not used by majestic
        src = MajesticMillionSource(
            limit    = limit,
            min_rank = min_rank,
            max_rank = max_rank,
        )

    elif source == "name":
        from ddig.sources.name import NameSource
        src = NameSource(headless=headless, verbose=verbose)

    else:
        console.print(f"[red]Unknown source: {source!r}[/red]")
        console.print("Valid sources: dropcatch, expireddomains, czds, majestic")
        raise typer.Exit(1)

    t0 = time.perf_counter()
    with console.status(f"[bold green]Fetching from {source}…"):
        domains = list(src.fetch())
    t_fetch = time.perf_counter() - t0
    console.print(
        f"[cyan]Fetched[/cyan] {len(domains):,} domains from [bold]{source}[/bold]  "
        f"[dim]({t_fetch:.1f}s)[/dim]"
    )

    if score and domains:
        scorer = DomainScorer(language="en")
        t0 = time.perf_counter()
        with console.status(f"[bold green]Scoring {len(domains):,} domains with NLP…"):
            domains = scorer.score_many(domains)
        t_score = time.perf_counter() - t0
        console.print(
            f"[cyan]Scoring complete.[/cyan]  "
            f"[dim]({t_score:.1f}s — {len(domains)/t_score:,.0f} domains/sec)[/dim]"
        )

    t0 = time.perf_counter()
    with console.status("[bold green]Saving to database…"):
        written = store.upsert_many(domains)
    t_save = time.perf_counter() - t0
    console.print(
        f"[green]✓[/green] Saved {written:,} records to [bold]{db}[/bold]  "
        f"[dim]({t_save:.1f}s)[/dim]"
    )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@app.command()
def search(
    name:          Optional[str]   = typer.Option(None,    "--name",          "-n",  help="Partial name match"),
    tld:           Optional[str]   = typer.Option(None,    "--tld",           "-t",  help="TLD filter e.g. com"),
    source:        Optional[str]   = typer.Option(None,    "--source",        "-s",  help="Filter by source: dropcatch | expireddomains | czds | majestic"),
    min_score:     Optional[float] = typer.Option(None,    "--min-score",            help="Min NLP score 0.0–1.0"),
    max_length:    Optional[int]   = typer.Option(None,    "--max-length",           help="Max name length"),
    min_backlinks: Optional[int]   = typer.Option(None,    "--min-backlinks",        help="Min backlink count (RefSubNets from Majestic)"),
    min_rank:      Optional[int]   = typer.Option(None,    "--min-rank",             help="Min Majestic GlobalRank"),
    max_rank:      Optional[int]   = typer.Option(None,    "--max-rank",             help="Max Majestic GlobalRank e.g. 10000 = top 10K only"),
    within:        Optional[int]   = typer.Option(None,    "--within",               help="Dropping within N days"),
    real_words:    bool            = typer.Option(False,   "--real-words",           help="Real English words only"),
    no_hyphens:    bool            = typer.Option(False,   "--no-hyphens",           help="Exclude domains with hyphens"),
    no_numbers:    bool            = typer.Option(False,   "--no-numbers",           help="Exclude domains with numbers"),
    sort:          str             = typer.Option(
        "composite",
        "--sort",
        help="Sort by: composite | score | rank | backlinks | drop",
    ),
    limit:         int             = typer.Option(50,      "--limit",         "-l",  help="Max results to return"),
    db:            Path            = typer.Option(DEFAULT_DB_PATH,            "--db"),
    verbose:       bool            = typer.Option(False,   "--verbose",       "-v"),
) -> None:
    """Search the local domain database."""
    _setup_logging(verbose)

    VALID_SORTS = {"composite", "score", "rank", "backlinks", "drop"}
    if sort not in VALID_SORTS:
        console.print(f"[red]Invalid --sort value: {sort!r}[/red]")
        console.print(f"Valid options: {', '.join(sorted(VALID_SORTS))}")
        raise typer.Exit(1)

    store   = DomainStore(db_path=db)
    domains = store.search(
        name          = name,
        tld           = tld,
        source        = source,
        min_score     = min_score,
        max_length    = max_length,
        min_backlinks = min_backlinks,
        min_rank      = min_rank,
        max_rank      = max_rank,
        within_days   = within,
        real_words    = real_words,
        no_hyphens    = no_hyphens,
        no_numbers    = no_numbers,
        sort          = sort,
        limit         = limit,
    )

    if not domains:
        console.print("[yellow]No domains found.[/yellow]")
        raise typer.Exit(0)

    # ------------------------------------------------------------------ #
    # Output table                                                         #
    # ------------------------------------------------------------------ #
    from rich.table import Table
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("FQDN",       style="bold white",  no_wrap=True)
    table.add_column("Score",      style="green",        justify="right", width=6)
    table.add_column("Backlinks",  style="cyan",         justify="right", width=10)
    table.add_column("Rank",       style="dim cyan",     justify="right", width=8)
    table.add_column("Drop",       style="yellow",       width=12)
    table.add_column("Source",     style="dim",          width=20)

    for d in domains:
        score     = f"{d.nlp_score:.2f}" if d.nlp_score is not None else "—"
        backlinks = f"{d.backlinks:,}"   if d.backlinks is not None else "—"
        rank      = f"{d.rank:,}"        if d.rank      is not None else "—"
        drop      = d.drop_date.strftime("%Y-%m-%d") if d.drop_date else "—"
        table.add_row(d.fqdn, score, backlinks, rank, drop, d.source)

    console.print(table)
    console.print(f"\n[dim]{len(domains)} result(s)[/dim]")


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

@app.command()
def score(
    language:   str  = typer.Option("en",           "--language", "-l"),
    batch_size: int  = typer.Option(10_000,          "--batch-size", help="Domains per scoring batch"),
    db:         Path = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose:    bool = typer.Option(False,           "--verbose",  "-v"),
) -> None:
    """Run NLP scoring on all unscored domains in the database."""
    _setup_logging(verbose)

    store  = DomainStore(db_path=db)
    scorer = DomainScorer(language=language)

    # Count unscored first
    all_domains  = store.search(limit=10_000_000)
    unscored     = [d for d in all_domains if d.nlp_score is None]
    total        = len(unscored)

    if not total:
        console.print("[green]✓[/green] All domains already scored.")
        return

    console.print(f"Scoring [bold]{total:,}[/bold] unscored domains in batches of {batch_size:,}…\n")

    scored_total = 0
    import time
    t0 = time.perf_counter()

    for i in range(0, total, batch_size):
        batch   = unscored[i : i + batch_size]
        scored  = scorer.score_many(batch)
        store.upsert_many(scored)
        scored_total += len(scored)
        elapsed      = time.perf_counter() - t0
        rate         = scored_total / elapsed if elapsed else 0
        console.print(
            f"  [cyan]{scored_total:>8,}[/cyan] / {total:,}  "
            f"[dim]({rate:,.0f}/sec — "
            f"~{(total - scored_total) / rate:.0f}s remaining)[/dim]"
            if rate else f"  {scored_total:,} / {total:,}"
        )

    elapsed = time.perf_counter() - t0
    console.print(
        f"\n[green]✓[/green] Scored [bold]{scored_total:,}[/bold] domains "
        f"in {elapsed:.1f}s  [dim]({scored_total/elapsed:,.0f}/sec)[/dim]"
    )


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@app.command()
def stats(
    db:      Path = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show statistics about the local database."""
    _setup_logging(verbose)

    store = DomainStore(db_path=db)
    s     = store.stats()

    table = Table(title="DDig Database Stats", header_style="bold magenta")
    table.add_column("Metric", style="cyan", min_width=20)
    table.add_column("Value",  style="green", justify="right")

    table.add_row("Total domains", f"{s['total']:,}")
    table.add_row("NLP scored",    f"{s['scored']:,}")

    table.add_row("─" * 20, "─" * 8)
    table.add_row("[bold]By Source[/bold]", "")
    for src, count in s["by_source"].items():
        table.add_row(f"  {src or 'unknown'}", f"{count:,}")

    table.add_row("─" * 20, "─" * 8)
    table.add_row("[bold]By TLD[/bold]", "")
    for tld, count in list(s["by_tld"].items())[:15]:
        table.add_row(f"  .{tld}", f"{count:,}")

    console.print(table)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@app.command()
def export(
    output:        Optional[Path]  = typer.Argument(None,   help="Output file — omit to print to stdout"),
    fmt:           str             = typer.Option("csv",    "--format", "-f",  help="csv or json"),
    tld:           Optional[str]   = typer.Option(None,     "--tld",    "-t"),
    source:        Optional[str]   = typer.Option(None,     "--source", "-s"),
    min_score:     Optional[float] = typer.Option(None,     "--min-score"),
    max_length:    Optional[int]   = typer.Option(None,     "--max-length"),
    min_backlinks: Optional[int]   = typer.Option(None,     "--min-backlinks"),
    max_rank:      Optional[int]   = typer.Option(None,     "--max-rank"),
    within:        Optional[int]   = typer.Option(None,     "--within",        help="Dropping within N days"),
    real_words:    bool            = typer.Option(False,    "--real-words"),
    no_hyphens:    bool            = typer.Option(False,    "--no-hyphens"),
    no_numbers:    bool            = typer.Option(False,    "--no-numbers"),
    sort:          str             = typer.Option("composite", "--sort",        help="composite | score | rank | backlinks | drop"),
    limit:         int             = typer.Option(10_000,   "--limit", "-l"),
    db:            Path            = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose:       bool            = typer.Option(False,    "--verbose", "-v"),
) -> None:
    """Export search results to CSV or JSON (file or stdout)."""
    _setup_logging(verbose)

    store   = DomainStore(db_path=db)
    results = store.search(
        tld           = tld,
        source        = source,
        min_score     = min_score,
        max_length    = max_length,
        min_backlinks = min_backlinks,
        max_rank      = max_rank,
        within_days   = within,
        real_words    = real_words,
        no_hyphens    = no_hyphens,
        no_numbers    = no_numbers,
        sort          = sort,
        limit         = limit,
    )

    if not results:
        console.print("[yellow]No results to export.[/yellow]")
        raise typer.Exit(0)

    def _rows():
        for d in results:
            yield {
                "fqdn":             d.fqdn,
                "name":             d.name,
                "tld":              d.tld,
                "length":           d.length,
                "drop_date":        d.drop_date.isoformat()   if d.drop_date   else "",
                "expiry_date":      d.expiry_date.isoformat() if d.expiry_date else "",
                "nlp_score":        d.nlp_score,
                "composite_score":  d.composite_score,
                "word_frequency":   d.word_frequency,
                "is_real_word":     d.is_real_word,
                "is_pronounceable": d.is_pronounceable,
                "backlinks":        d.backlinks,
                "rank":             d.rank,
                "tags":             "|".join(d.tags),
                "registrar":        d.registrar,
                "source":           d.source,
            }

    import sys

    if fmt == "csv":
        fh       = open(output, "w", newline="", encoding="utf-8") if output else sys.stdout  # type: ignore[assignment]
        rows     = list(_rows())
        writer   = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        if output:
            fh.close()

    elif fmt == "json":
        data = list(_rows())
        if output:
            Path(output).write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            print(json.dumps(data, indent=2))

    else:
        console.print(f"[red]Unknown format: {fmt!r}. Use csv or json.[/red]")
        raise typer.Exit(1)

    if output:
        console.print(
            f"[green]✓[/green] Exported {len(results):,} domains to [bold]{output}[/bold]"
        )


# ---------------------------------------------------------------------------
# czds_tlds
# ---------------------------------------------------------------------------

@app.command()
def czds_tlds(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """List all CZDS TLDs approved for download."""
    _setup_logging(verbose)

    from .sources.czds import CZDSSource
    src      = CZDSSource()
    approved = src._get_approved_tlds()

    console.print(f"\n[bold]Approved TLDs[/bold] — {len(approved):,} ready to download\n")

    if not approved:
        console.print(
            "  [yellow]None yet — request access at "
            "https://czds.icann.org/zone-requests/new[/yellow]"
        )
        return

    # Print in columns sorted alphabetically
    from rich.columns import Columns
    console.print(Columns(
        [f"[green].{t}[/green]" for t in sorted(approved)],
        equal=True,
        expand=False,
    ))
    console.print(f"\n[dim]Run [bold]ddig fetch --source czds --tlds <tld>[/bold] to download a zone file.[/dim]\n")

# ---------------------------------------------------------------------------

@app.command()
def czds_auth(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """
    Re-authenticate with ICANN CZDS via Playwright and save fresh token to .env.

    Opens a browser window — complete any MFA prompts manually.
    The token is captured automatically and written to .env.
    """
    _setup_logging(verbose)

    console.print("\n[bold]CZDS Re-authentication[/bold]\n")
    console.print("A browser window will open. Log in and complete any MFA prompts.")
    console.print("The JWT will be captured automatically and saved to [bold].env[/bold].\n")

    from .sources.czds import CZDSSource
    source = CZDSSource()

    # Force Playwright auth by clearing any cached token
    source.token = ""
    source._jwt  = None

    try:
        token = source._playwright_auth()
        source._save_token_to_env(token)
        console.print(f"\n[green]✓[/green] Token captured ({len(token)} chars) and saved to .env")
        console.print("[dim]Run [bold]ddig czds-tlds[/bold] to verify access.[/dim]")
    except Exception as exc:
        console.print(f"[red]✗[/red] Authentication failed: {exc}")
        raise typer.Exit(1)

# ---------------------------------------------------------------------------

@app.command()
def doctor(
    db:      Path = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Check environment, credentials, dependencies, CLI tools, git hooks, and database."""
    _setup_logging(verbose)

    console.print("\n[bold]DDig Environment Check[/bold]\n")

    # ── Python / venv ──────────────────────────────────────────────
    import sys
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim",   min_width=24)
    table.add_column(min_width=50)

    table.add_row("Python",     sys.executable)
    table.add_row("Version",    sys.version.split()[0])
    console.print(table)
    console.print()

    # ── .env loading ───────────────────────────────────────────────
    console.print("[bold]dotenv[/bold]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim",  min_width=24)
    table.add_column(min_width=50)

    try:
        from dotenv import load_dotenv, find_dotenv
        found = find_dotenv(usecwd=True)
        loaded = load_dotenv(found, override=False)
        table.add_row("python-dotenv", "[green]✓ installed[/green]")
        table.add_row(".env found",    f"[green]✓[/green] {found}" if found else "[red]✗ not found[/red]")
        table.add_row(".env loaded",   "[green]✓ yes[/green]" if loaded else "[yellow]⚠ already loaded or empty[/yellow]")
    except ImportError:
        table.add_row("python-dotenv", "[red]✗ not installed — run: pip install python-dotenv[/red]")
    console.print(table)
    console.print()

    # ── Credentials ────────────────────────────────────────────────
    import os
    console.print("[bold]Credentials[/bold]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim",  min_width=28)
    table.add_column(min_width=50)

    def _check(key: str, secret: bool = True) -> str:
        val = os.environ.get(key, "")
        if not val:
            return "[red]✗ not set[/red]"
        display = f"{val[:4]}... ({len(val)} chars)" if secret else val
        return f"[green]✓[/green] {display}"

    table.add_row("EXPIREDDOMAINS_USER",            _check("EXPIREDDOMAINS_USER",            secret=False))
    table.add_row("EXPIREDDOMAINS_PASS",            _check("EXPIREDDOMAINS_PASS",            secret=True))
    table.add_row("EXPIREDDOMAINS_SESSION_NAME",    _check("EXPIREDDOMAINS_SESSION_NAME",    secret=False))
    table.add_row("EXPIREDDOMAINS_SESSION",         _check("EXPIREDDOMAINS_SESSION",         secret=True))
    table.add_row("EXPIREDDOMAINS_REMEMBER_COOKIE_NAME", _check("EXPIREDDOMAINS_REMEMBER_COOKIE_NAME", secret=False))
    table.add_row("EXPIREDDOMAINS_REMEMBER_SESSION",_check("EXPIREDDOMAINS_REMEMBER_SESSION",secret=True))
    table.add_row("CZDS_USER",                      _check("CZDS_USER",                      secret=False))
    table.add_row("CZDS_PASS",                      _check("CZDS_PASS",                      secret=True))
    table.add_row("CZDS_TOKEN",                     _check("CZDS_TOKEN",                     secret=True))
    table.add_row("NAME_USER",                      _check("NAME_USER",                      secret=False))
    table.add_row("NAME_PASS",                      _check("NAME_PASS",                      secret=True))
    table.add_row("NAME_SESSION",                   _check("NAME_SESSION",                   secret=True))
    table.add_row("NAME_LOGIN_TIME",                _check("NAME_LOGIN_TIME",                secret=True))

    console.print(table)
    console.print()

    # ── Dependencies ───────────────────────────────────────────────
    console.print("[bold]Dependencies[/bold]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", min_width=24)
    table.add_column(min_width=50)

    def _dep(pkg: str) -> str:
        try:
            importlib.metadata.version(pkg)
            return "[green]✓ installed[/green]"
        except importlib.metadata.PackageNotFoundError:
            return f"[red]✗ not installed — run: pip install {pkg}[/red]"

    table.add_row("playwright",  _dep("playwright"))
    table.add_row("sqlalchemy",  _dep("sqlalchemy"))
    table.add_row("rich",        _dep("rich"))
    table.add_row("requests",    _dep("requests"))

    console.print(table)
    console.print()

    # ── Database ───────────────────────────────────────────────────
    console.print("[bold]Database[/bold]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim", min_width=24)
    table.add_column(min_width=50)

    table.add_row("Path", str(db))
    try:
        _store = DomainStore(db_path=db)
        _s     = _store.stats()
        table.add_row("Total domains", f"{_s['total']:,}")
        table.add_row("NLP scored",    f"{_s['scored']:,}")
    except Exception as exc:
        table.add_row("Status", f"[red]✗ could not open DB: {exc}[/red]")

    console.print(table)
    console.print()

# ---------------------------------------------------------------------------
# ed_debug
# ---------------------------------------------------------------------------

@app.command()
def ed_debug(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Debug ExpiredDomains login form — shows actual input field names/IDs."""
    _setup_logging(verbose)

    from .sources.expireddomains import ExpiredDomainsSource, BASE_URL, NAV_TIMEOUT
    from playwright.sync_api import sync_playwright

    console.print("\n[bold]ExpiredDomains Login Form Debug[/bold]\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context()
        page    = context.new_page()

        console.print(f"Navigating to {BASE_URL}/login/ …")
        page.goto(f"{BASE_URL}/login/", timeout=NAV_TIMEOUT)
        page.wait_for_load_state("networkidle")

        # Dump every input field on the page
        inputs = page.query_selector_all("input")
        console.print(f"\nFound [bold]{len(inputs)}[/bold] input fields:\n")

        table = Table(header_style="bold magenta")
        table.add_column("type",        style="cyan",   width=12)
        table.add_column("name",        style="green",  width=20)
        table.add_column("id",          style="yellow", width=20)
        table.add_column("placeholder", style="dim",    width=30)
        table.add_column("selector",    style="white",  width=40)

        for inp in inputs:
            itype  = inp.get_attribute("type")        or ""
            iname  = inp.get_attribute("name")        or ""
            iid    = inp.get_attribute("id")          or ""
            iplace = inp.get_attribute("placeholder") or ""

            # Build the most specific usable selector
            if iid:
                selector = f"#{iid}"
            elif iname:
                selector = f'input[name="{iname}"]'
            else:
                selector = f'input[type="{itype}"]'

            table.add_row(itype, iname, iid, iplace, selector)

        console.print(table)

        # Also dump any forms
        forms = page.query_selector_all("form")
        console.print(f"\nFound [bold]{len(forms)}[/bold] form(s):\n")
        for i, form in enumerate(forms):
            action = form.get_attribute("action") or ""
            method = form.get_attribute("method") or ""
            fid    = form.get_attribute("id")     or ""
            console.print(f"  Form {i}: id={fid!r}  action={action!r}  method={method!r}")

        console.print("\n[dim]Browser staying open — press Ctrl+C to close.[/dim]")
        input()  # keep browser open so you can inspect
        browser.close()


# ---------------------------------------------------------------------------
# name_debug
# ---------------------------------------------------------------------------

@app.command()
def name_debug(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """
    Open a Playwright browser to inspect the name.com login form fields.

    Navigates to the sign-in page, prints all input field attributes,
    then waits for you to inspect the browser before closing.
    Useful when login breaks and selectors need updating.
    """
    _setup_logging(verbose)

    console.print("\n[bold]name.com Login Form Debug[/bold]\n")
    console.print("Opening browser and printing all input fields...\n")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page    = browser.new_page()
        page.goto("https://www.name.com/account/login", wait_until="domcontentloaded")
        page.wait_for_selector("input[name='acct_name']", timeout=10000)

        from rich.table import Table as RichTable
        inputs = page.query_selector_all("input")
        if not inputs:
            console.print("[yellow]No input fields found on the page.[/yellow]")
        else:
            table = RichTable(title="Input Fields", show_header=True)
            table.add_column("type",        style="cyan")
            table.add_column("name",        style="green")
            table.add_column("id",          style="yellow")
            table.add_column("placeholder", style="dim")
            for inp in inputs:
                table.add_row(
                    inp.get_attribute("type")        or "",
                    inp.get_attribute("name")        or "",
                    inp.get_attribute("id")          or "",
                    inp.get_attribute("placeholder") or "",
                )
            console.print(table)

        buttons = page.query_selector_all("button")
        btable = RichTable(title="Buttons", show_header=True)
        btable.add_column("type",    style="cyan")
        btable.add_column("class",   style="green")
        btable.add_column("text",    style="yellow")
        btable.add_column("visible", style="dim")
        for btn in buttons:
            btable.add_row(
                btn.get_attribute("type")  or "",
                btn.get_attribute("class") or "",
                (btn.inner_text() or "").strip()[:40],
                str(btn.is_visible()),
            )
        console.print(btable)

        console.print("\n[dim]Browser is open — inspect as needed. Press Enter here to close.[/dim]")
        input()
        browser.close()

    console.print("[green]✓[/green] Done.")


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------

@app.command()
def purge(
    db:      Path = typer.Option(DEFAULT_DB_PATH, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted without deleting"),
) -> None:
    """Remove domains with no drop_date from the database."""
    _setup_logging(verbose)
    store = DomainStore(db_path=db)

    if dry_run:
        from sqlalchemy import text
        with store.engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM domains WHERE drop_date IS NULL")).scalar()
        console.print(f"[yellow]dry-run:[/yellow] would delete {count:,} domains with no drop_date")
        return

    count = store.purge_no_drop_date()
    console.print(f"[green]✓[/green] Purged [bold]{count:,}[/bold] domains with no drop_date")

# ---------------------------------------------------------------------------

def main() -> None:
    app()


if __name__ == "__main__":
    main()
