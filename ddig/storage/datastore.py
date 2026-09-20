"""
SQLite-backed domain store via SQLAlchemy.

Provides fast lookups by name, TLD, expiry date, and NLP score.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, cast, Iterable

from sqlalchemy import (
    and_,
    case,
    or_,
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    func,
    insert,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ..models.domain import Domain

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".ddig" / "domains.db"

# How many rows to insert per batch
BATCH_SIZE = 2_000


class Base(DeclarativeBase):
    pass


class DomainRecord(Base):
    """SQLAlchemy ORM model — one row per unique FQDN."""

    __tablename__ = "domains"

    id                 = Column(Integer,      primary_key=True, autoincrement=True)
    fqdn               = Column(String(253),  unique=True, nullable=False)
    name               = Column(String(63),   nullable=False)
    tld                = Column(String(63),   nullable=False)
    expiry_date        = Column(String(32),   nullable=True)
    drop_date          = Column(String(32),   nullable=True)
    source             = Column(String(64),   nullable=True)
    registrar          = Column(String(128),  nullable=True)
    backlinks          = Column(Integer,      nullable=True)
    rank               = Column(Integer,      nullable=True)   # GlobalRank from Majestic etc.
    nlp_score          = Column(Float,        nullable=True)
    composite_score    = Column(Float,        nullable=True)
    is_real_word       = Column(Integer,      nullable=True)   # bool as 0/1
    word_frequency     = Column(Float,        nullable=True)
    is_pronounceable   = Column(Integer,      nullable=True)
    tags               = Column(Text,         nullable=True)   # JSON array
    fetched_at         = Column(String(32),   nullable=True)

    __table_args__ = (
        Index("idx_tld",       "tld"),
        Index("idx_name",      "name"),
        Index("idx_expiry",    "expiry_date"),
        Index("idx_drop",      "drop_date"),
        Index("idx_nlp_score", "nlp_score"),
        Index("idx_source",    "source"),
        Index("idx_backlinks", "backlinks"),
        Index("idx_rank",      "rank"),
    )


class WatchlistRecord(Base):
    """Watched domains — pinned for monitoring regardless of drop date."""

    __tablename__ = "watchlist"

    fqdn     = Column(String(253), primary_key=True, nullable=False)
    added_at = Column(String(32),  nullable=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _domain_to_record(domain: Domain) -> dict:
    """Convert a Domain dataclass to a dict for SQLite insert."""
    # Compute composite_score if nlp_score is available and composite not already set
    composite = domain.composite_score
    if composite is None and domain.nlp_score is not None:
        from ddig.nlp.scorer import compute_composite
        composite = compute_composite(
            domain.nlp_score,
            domain.backlinks,
            domain.rank,
        )

    return {
        "fqdn":             domain.fqdn,
        "name":             domain.name,
        "tld":              domain.tld,
        "source":           domain.source or "",
        "registrar":        domain.registrar,
        "expiry_date":      domain.expiry_date.isoformat() if domain.expiry_date else None,
        "drop_date":        domain.drop_date.isoformat()   if domain.drop_date   else None,
        "backlinks":        domain.backlinks,
        "rank":             domain.rank,
        "nlp_score":        domain.nlp_score,
        "composite_score":  composite,
        "is_real_word":     domain.is_real_word,
        "word_frequency":   domain.word_frequency,
        "is_pronounceable": domain.is_pronounceable,
        "tags":             json.dumps(domain.tags) if domain.tags else None,
        "fetched_at":       datetime.now(timezone.utc).isoformat(),
    }


def _record_to_domain(rec: DomainRecord) -> Domain:
    def _parse_dt(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    name = cast(str, rec.name)
    tld = cast(str, rec.tld)
    fqdn = cast(str, rec.fqdn)
    expiry_date = cast(str | None, rec.expiry_date)
    drop_date = cast(str | None, rec.drop_date)
    source = cast(str | None, rec.source)
    registrar = cast(str | None, rec.registrar)
    backlinks = cast(int | None, rec.backlinks)
    nlp_score = cast(float | None, rec.nlp_score)
    composite_score = cast(float | None, rec.composite_score)
    is_real_word = cast(int | None, rec.is_real_word)
    word_frequency = cast(float | None, rec.word_frequency)
    is_pronounceable = cast(int | None, rec.is_pronounceable)
    tags = cast(str | None, rec.tags)
    fetched_at = cast(str | None, rec.fetched_at)
    rank = cast(int | None, rec.rank)

    return Domain(
        name             = name,
        tld              = tld,
        fqdn             = fqdn,
        expiry_date      = _parse_dt(expiry_date),
        drop_date        = _parse_dt(drop_date),
        source           = source or "",
        registrar        = registrar,
        backlinks        = backlinks,
        nlp_score        = nlp_score,
        composite_score  = composite_score,
        is_real_word     = bool(is_real_word)     if is_real_word     is not None else None,
        word_frequency   = word_frequency,
        is_pronounceable = bool(is_pronounceable) if is_pronounceable is not None else None,
        tags             = json.loads(tags) if tags else [],
        fetched_at       = _parse_dt(fetched_at) or datetime.now(timezone.utc),  # fixed
        rank             = rank,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class DomainStore:
    """
    Persistent SQLite store for Domain records.

    Usage::

        store = DomainStore()
        store.upsert_many(domains)
        results = store.search(tld="com", min_score=0.7)
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # SQLite performance pragmas — applied on every new connection
        @event.listens_for(self.engine, "connect")
        def set_pragmas(conn, _record):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")   # 64 MB page cache
            conn.execute("PRAGMA temp_store=MEMORY")

        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)
        log.info("DomainStore opened at %s", db_path)

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    def upsert(self, domain: Domain) -> None:
        """Insert or update a single domain."""
        self.upsert_many([domain])

    def upsert_many(self, domains: list[Domain]) -> int:
        """
        Bulk upsert using SQLite INSERT OR REPLACE.
        On conflict (same fqdn):
          - Always update: source, drop_date, expiry_date, fetched_at
          - backlinks: keep highest value seen
          - rank:      keep lowest (best) value seen
          - nlp_score + NLP fields: never overwrite once scored
          - composite_score: recomputed whenever nlp_score, backlinks, or rank change
        Returns the number of domains processed.
        """
        if not domains:
            return 0

        records = [_domain_to_record(d) for d in domains]
        total   = len(records)

        with self.engine.begin() as conn:
            for i in range(0, total, BATCH_SIZE):
                batch = records[i : i + BATCH_SIZE]
                stmt  = sqlite_insert(DomainRecord).values(batch)

                # Resolved backlinks — highest value wins
                resolved_backlinks = case(
                    (
                        and_(
                            stmt.excluded.backlinks.isnot(None),
                            or_(
                                DomainRecord.backlinks.is_(None),
                                stmt.excluded.backlinks > DomainRecord.backlinks,
                            ),
                        ),
                        stmt.excluded.backlinks,
                    ),
                    else_=DomainRecord.backlinks,
                )

                # Resolved rank — lowest (best) value wins
                resolved_rank = case(
                    (
                        and_(
                            stmt.excluded.rank.isnot(None),
                            or_(
                                DomainRecord.rank.is_(None),
                                stmt.excluded.rank < DomainRecord.rank,
                            ),
                        ),
                        stmt.excluded.rank,
                    ),
                    else_=DomainRecord.rank,
                )

                # Resolved nlp_score — never overwrite once set
                resolved_nlp = case(
                    (DomainRecord.nlp_score.is_(None), stmt.excluded.nlp_score),
                    else_=DomainRecord.nlp_score,
                )

                # composite_score — recompute whenever we have an nlp_score
                # Formula mirrors compute_composite():
                #   50% nlp + 30% log-normalised backlinks + 20% inverse log-normalised rank
                # SQLite has no log() — use pre-computed Python constants as scale factors:
                #   log10(1_000_000) = 6.0
                _LOG_CEIL = 6.0   # log10(1_000_000)

                resolved_composite = case(
                    # Only compute if nlp_score is available
                    (
                        resolved_nlp.isnot(None),
                        (
                            resolved_nlp * 0.50
                            + case(
                                (
                                    and_(resolved_backlinks.isnot(None), resolved_backlinks > 0),
                                    # log10 not available in SQLite — approximate with
                                    # Python-side value stored in composite on next ddig score
                                    # For upsert we use a simplified linear proxy capped at 1.0
                                    func.min(
                                        func.log(resolved_backlinks + 1) / _LOG_CEIL,
                                        1.0,
                                    ) * 0.30,
                                ),
                                else_=0.0,
                            )
                            + case(
                                (
                                    and_(resolved_rank.isnot(None), resolved_rank > 0),
                                    func.max(
                                        1.0 - func.log(resolved_rank) / _LOG_CEIL,
                                        0.0,
                                    ) * 0.20,
                                ),
                                else_=0.0,
                            )
                        ),
                    ),
                    else_=DomainRecord.composite_score,
                )

                on_conflict_dict = {
                    "source": case(
                        (
                            ~DomainRecord.source.contains(stmt.excluded.source),
                            DomainRecord.source + "," + stmt.excluded.source,
                        ),
                        else_=DomainRecord.source,
                    ),
                    "fetched_at":       stmt.excluded.fetched_at,
                    "name":             stmt.excluded.name,
                    "tld":              stmt.excluded.tld,
                    "registrar":        stmt.excluded.registrar,
                    "expiry_date":      stmt.excluded.expiry_date,
                    "drop_date":        stmt.excluded.drop_date,
                    "backlinks":        resolved_backlinks,
                    "rank":             resolved_rank,
                    "nlp_score":        resolved_nlp,
                    "composite_score":  resolved_composite,
                    "is_real_word": case(
                        (DomainRecord.nlp_score.is_(None), stmt.excluded.is_real_word),
                        else_=DomainRecord.is_real_word,
                    ),
                    "word_frequency": case(
                        (DomainRecord.nlp_score.is_(None), stmt.excluded.word_frequency),
                        else_=DomainRecord.word_frequency,
                    ),
                    "is_pronounceable": case(
                        (DomainRecord.nlp_score.is_(None), stmt.excluded.is_pronounceable),
                        else_=DomainRecord.is_pronounceable,
                    ),
                    "tags": case(
                        (DomainRecord.nlp_score.is_(None), stmt.excluded.tags),
                        else_=DomainRecord.tags,
                    ),
                }

                stmt = stmt.on_conflict_do_update(
                    index_elements=["fqdn"],
                    set_=on_conflict_dict,
                )

                conn.execute(stmt)
                log.debug("Upserted batch %d–%d", i, i + len(batch))

        log.debug("Upserted %d domains total", total)
        return total

    # ------------------------------------------------------------------ #
    # Read / Search                                                        #
    # ------------------------------------------------------------------ #

    def search(
        self,
        *,
        name:          Optional[str]   = None,
        tld:           Optional[str]   = None,
        source:        Optional[str]   = None,
        min_score:     Optional[float] = None,
        max_length:    Optional[int]   = None,
        min_backlinks: Optional[int]   = None,
        min_rank:      Optional[int]   = None,
        max_rank:      Optional[int]   = None,
        within_days:   Optional[int]   = None,
        real_words:    bool            = False,
        no_hyphens:    bool            = False,
        no_numbers:    bool            = False,
        sort:          str             = "composite",   # composite | score | rank | backlinks | drop
        limit:         int             = 50,
    ) -> list[Domain]:
        with self._Session() as session:
            q = select(DomainRecord)

            if name:
                q = q.where(DomainRecord.name.ilike(f"%{name}%"))
            if tld:
                q = q.where(DomainRecord.tld == tld.lstrip(".").lower())
            if source:
                q = q.where(DomainRecord.source.ilike(f"%{source}%"))
            if min_score is not None:
                q = q.where(DomainRecord.nlp_score >= min_score)
            if max_length is not None:
                q = q.where(func.length(DomainRecord.name) <= max_length)
            if min_backlinks is not None:
                q = q.where(DomainRecord.backlinks >= min_backlinks)
            if min_rank is not None:
                q = q.where(DomainRecord.rank >= min_rank)
            if max_rank is not None:
                q = q.where(DomainRecord.rank <= max_rank)
            if within_days is not None:

                now    = datetime.now(timezone.utc)
                cutoff = now + timedelta(days=within_days)
                q = q.where(DomainRecord.drop_date.isnot(None))
                q = q.where(DomainRecord.drop_date >= now.isoformat())
                q = q.where(DomainRecord.drop_date <= cutoff.isoformat())

            if real_words:
                q = q.where(DomainRecord.is_real_word == True)
            if no_hyphens:
                q = q.where(DomainRecord.name.notlike("%-%"))
            if no_numbers:
                q = q.where(
                    ~func.lower(DomainRecord.name).op("GLOB")("*[0-9]*")
                )

            # Sort order
            if sort == "rank":
                q = q.order_by(DomainRecord.rank.asc().nulls_last())
            elif sort == "backlinks":
                q = q.order_by(DomainRecord.backlinks.desc().nulls_last())
            elif sort == "drop":
                q = q.order_by(DomainRecord.drop_date.asc().nulls_last())
            elif sort == "score":
                q = q.order_by(DomainRecord.nlp_score.desc().nulls_last())
            else:  # default: composite
                q = q.order_by(DomainRecord.composite_score.desc().nulls_last())

            q = q.limit(limit)

            rows = session.execute(q).scalars().all()
            return [_record_to_domain(r) for r in rows]

    def count(self) -> int:
        with self._Session() as session:
            return session.query(DomainRecord).count()

    def stats(self) -> dict:
        """Return a summary of the store contents."""
        from sqlalchemy import text

        with self.engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM domains")
            ).scalar()

            scored = conn.execute(
                text("SELECT COUNT(*) FROM domains WHERE nlp_score IS NOT NULL")
            ).scalar()

            tld_rows = conn.execute(
                text("SELECT tld, COUNT(*) as cnt FROM domains GROUP BY tld ORDER BY cnt DESC")
            ).fetchall()

            source_rows = conn.execute(
                text("""
                    SELECT
                        CASE
                            WHEN source LIKE '%dropcatch%'      THEN 'dropcatch'
                            WHEN source LIKE '%expireddomains%' THEN 'expireddomains'
                            WHEN source LIKE '%czds%'           THEN 'czds'
                            ELSE source
                        END as src,
                        COUNT(*) as cnt
                    FROM domains
                    GROUP BY src
                    ORDER BY cnt DESC
                """)
            ).fetchall()

        return {
            "total":     total,
            "scored":    scored,
            "by_tld":    {row[0]: row[1] for row in tld_rows},
            "by_source": {row[0]: row[1] for row in source_rows},
        }

    def get_all_fqdns(self) -> frozenset[str]:
        """Return all FQDNs currently in the store as a frozenset for fast lookup."""
        with self.engine.connect() as conn:
            from sqlalchemy import text
            rows = conn.execute(text("SELECT fqdn FROM domains")).fetchall()
        return frozenset(row[0] for row in rows)

    # ------------------------------------------------------------------ #
    # Watchlist                                                            #
    # ------------------------------------------------------------------ #

    def watch_add(self, fqdns: list[str]) -> list[str]:
        """Pin domains to the watchlist. Returns list of newly added FQDNs."""
        added = []
        now   = datetime.now(timezone.utc).isoformat()
        with self.engine.begin() as conn:
            for fqdn in fqdns:
                normalised = fqdn.lower().strip()
                stmt       = sqlite_insert(WatchlistRecord).values(
                    fqdn=normalised, added_at=now
                ).on_conflict_do_nothing(index_elements=["fqdn"])
                result = conn.execute(stmt)
                if result.rowcount:
                    added.append(normalised)
        return added

    def watch_remove(self, fqdns: list[str]) -> list[str]:
        """Unpin domains from the watchlist. Returns list of removed FQDNs."""
        from sqlalchemy import delete as sa_delete
        removed = []
        with self.engine.begin() as conn:
            for fqdn in fqdns:
                stmt   = sa_delete(WatchlistRecord).where(
                    WatchlistRecord.fqdn == fqdn.lower().strip()
                )
                result = conn.execute(stmt)
                if result.rowcount:
                    removed.append(fqdn)
        return removed

    def watch_list(self) -> list[dict]:
        """Return all watched domains with their domain record if available."""
        with self._Session() as session:
            rows = session.execute(
                select(WatchlistRecord).order_by(WatchlistRecord.added_at.desc())
            ).scalars().all()

            results = []
            for w in rows:
                domain_row = session.execute(
                    select(DomainRecord).where(DomainRecord.fqdn == w.fqdn)
                ).scalar_one_or_none()
                results.append({
                    "fqdn":     w.fqdn,
                    "added_at": w.added_at,
                    "domain":   _record_to_domain(domain_row) if domain_row else None,
                })
            return results

    def watch_clear(self) -> int:
        """Remove all entries from the watchlist. Returns count removed."""
        from sqlalchemy import delete as sa_delete
        with self.engine.begin() as conn:
            result = conn.execute(sa_delete(WatchlistRecord))
        return result.rowcount

    def purge_no_drop_date(self) -> int:
        """Remove all domains where drop_date is NULL. Returns count deleted."""
        from sqlalchemy import text
        with self.engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM domains WHERE drop_date IS NULL")
            )
            count = result.rowcount
            log.debug("Purged %d domains with no drop_date", count)
            return count

    def purge_fqdns(self, fqdns: Iterable[str], skip: frozenset[str] | None = None) -> int:
        """
        Delete domains by FQDN. Optionally skip a set of protected FQDNs.

        Args:
            fqdns: Iterable of FQDNs to delete.
            skip:  FQDNs to protect from deletion (e.g. watchlist).

        Returns:
            Number of rows deleted.
        """
        from sqlalchemy import text
        skip = skip or frozenset()
        to_delete = [f for f in fqdns if f not in skip]

        if not to_delete:
            return 0

        total = 0
        with self.engine.begin() as conn:
            for i in range(0, len(to_delete), BATCH_SIZE):
                batch       = to_delete[i : i + BATCH_SIZE]
                placeholders = ",".join(f":f{j}" for j in range(len(batch)))
                params       = {f"f{j}": fqdn for j, fqdn in enumerate(batch)}
                result       = conn.execute(
                    text(f"DELETE FROM domains WHERE fqdn IN ({placeholders})"),
                    params,
                )
                total += result.rowcount
                log.debug("Purged batch %d–%d (%d deleted)", i, i + len(batch), result.rowcount)

        log.debug("purge_fqdns: deleted %d domains total", total)
        return total

    def get_watchlist_fqdns(self) -> frozenset[str]:
        """Return all watchlisted FQDNs as a frozenset for fast lookup."""
        with self.engine.connect() as conn:
            from sqlalchemy import text
            rows = conn.execute(text("SELECT fqdn FROM watchlist")).fetchall()
        return frozenset(row[0] for row in rows)