"""
SQLite-backed domain store via SQLAlchemy.

Provides fast lookups by name, TLD, expiry date, and NLP score.
"""
from __future__ import annotations

import json
import logging
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _domain_to_record(domain: Domain) -> dict:
    return dict(
        fqdn              = domain.fqdn,
        name              = domain.name,
        tld               = domain.tld,
        expiry_date       = _dt_str(domain.expiry_date),
        drop_date         = _dt_str(domain.drop_date),
        source            = domain.source,
        registrar         = domain.registrar,
        backlinks         = domain.backlinks,
        nlp_score         = domain.nlp_score,
        composite_score   = domain.composite_score,
        is_real_word      = int(domain.is_real_word)      if domain.is_real_word      is not None else None,
        word_frequency    = domain.word_frequency,
        is_pronounceable  = int(domain.is_pronounceable)  if domain.is_pronounceable  is not None else None,
        tags              = json.dumps(domain.tags),
        fetched_at        = _dt_str(domain.fetched_at),
        rank              = domain.rank,
    )


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

    def upsert_many(self, domains: Iterable[Domain]) -> int:
        """
        Bulk upsert using SQLite INSERT OR REPLACE.
        On conflict (same fqdn):
          - Always update: source, drop_date, expiry_date, fetched_at
          - Only update if NULL: nlp_score, backlinks, registrar
            (preserve existing scored/enriched data)
        """
        if not domains:
            return 0

        # NLP columns — only fields that actually exist on DomainRecord
        # and should be preserved once scored
        NLP_COLS = [
            "nlp_score",
            "is_real_word",
            "word_frequency",
            "is_pronounceable",
            "tags",
        ]

        records = [_domain_to_record(d) for d in domains]
        total   = len(records)

        with self.engine.begin() as conn:
            for i in range(0, total, BATCH_SIZE):
                batch = records[i : i + BATCH_SIZE]
                stmt  = sqlite_insert(DomainRecord).values(batch)

                on_conflict_dict = {
                    "source": case(
                        (
                            ~DomainRecord.source.contains(stmt.excluded.source),
                            DomainRecord.source + "," + stmt.excluded.source,
                        ),
                        else_=DomainRecord.source,
                    ),
                    "fetched_at":  stmt.excluded.fetched_at,
                    "name":        stmt.excluded.name,
                    "tld":         stmt.excluded.tld,
                    "registrar":   stmt.excluded.registrar,
                    "expiry_date": stmt.excluded.expiry_date,
                    "backlinks": case(
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
                    ),
                    "rank": case(
                        (
                            and_(
                                stmt.excluded.rank.isnot(None),
                                or_(
                                    DomainRecord.rank.is_(None),
                                    stmt.excluded.rank < DomainRecord.rank,  # lower = better
                                ),
                            ),
                            stmt.excluded.rank,
                        ),
                        else_=DomainRecord.rank,
                    ),
                    "nlp_score": case(
                        (DomainRecord.nlp_score.is_(None), stmt.excluded.nlp_score),
                        else_=DomainRecord.nlp_score,
                    ),
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
                now        = datetime.now(timezone.utc)
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                cutoff     = now + timedelta(days=within_days)
                q = q.where(DomainRecord.drop_date <= cutoff.isoformat())
                q = q.where(DomainRecord.drop_date >= today_start.isoformat())

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