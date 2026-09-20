# DDig — Core Data Flow

```mermaid
sequenceDiagram
    actor User
    participant CLI as ddig CLI
    participant SRC as Source
    participant SCR as DomainScorer
    participant DB  as DomainStore

    User->>CLI: ddig fetch --source <name> [--score]

    Note over SRC: dropcatch — XML feed, no auth<br/>expireddomains — Playwright scraper<br/>czds — ICANN zone files, JWT auth<br/>majestic — CSV enrichment only<br/>name — name.com, cookie auth<br/>snapnames — CSV feeds, no auth<br/>parkio — JSON API, no auth

    CLI->>SRC: source.fetch()
    SRC-->>CLI: Iterator[Domain]

    alt --score flag set
        CLI->>SCR: scorer.score_many(domains)
        SCR-->>CLI: List[Domain] with nlp_score
    end

    CLI->>DB: store.upsert_many(domains)
    DB-->>CLI: count written

    CLI-->>User: Rich table summary
```

### Purge-registered path (NRD)

```mermaid
sequenceDiagram
    actor User
    participant CLI as ddig CLI
    participant NRD as NRDSource
    participant DB  as DomainStore

    User->>CLI: ddig purge-registered [--source all] [--dry-run]
    CLI->>NRD: source.fetch()
    NRD-->>CLI: Iterator[str] (FQDNs from cenk/nrd + WhoisDS)
    Note over NRD: Raw files saved to data/nrd/<timestamp>_*.txt/.zip
    CLI->>DB: store.get_all_fqdns()
    DB-->>CLI: frozenset[str]
    CLI->>DB: store.get_watchlist_fqdns()
    DB-->>CLI: frozenset[str]
    Note over CLI: matched = registered ∩ db_fqdns − watchlisted
    alt --dry-run
        CLI-->>User: Shows matches, no deletion
    else live run
        CLI->>DB: store.purge_fqdns(to_delete, skip=watchlisted)
        DB-->>CLI: count deleted
        CLI-->>User: Rich summary
    end
```

### Enrichment-only path (Majestic)

```mermaid
sequenceDiagram
    actor User
    participant CLI as ddig CLI
    participant MAJ as MajesticMillionSource
    participant DB  as DomainStore

    User->>CLI: ddig fetch --source majestic
    CLI->>DB: store.get_all_fqdns()
    DB-->>CLI: set[str]
    CLI->>MAJ: source.fetch()
    MAJ-->>CLI: Iterator[Domain] (filtered to existing fqdns only)
    CLI->>DB: store.upsert_many(domains)
    DB-->>CLI: count enriched
    CLI-->>User: Rich table summary