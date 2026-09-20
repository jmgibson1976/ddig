# DDig — Composite Score Formula

```mermaid
flowchart TD
    A([Domain record]) --> B{nlp_score\nis not None?}
    B -- No --> C([composite_score = NULL\nSkip — not scored yet])

    B -- Yes --> D[nlp_component = nlp_score × 0.50]

    D --> E{backlinks\nis not None\nand > 0?}
    E -- Yes --> F["backlinks_norm = log10(backlinks) / log10(max_expected)\nclamped to 0..1\nbacklinks_component = backlinks_norm × 0.30"]
    E -- No --> G[backlinks_component = 0.0]

    F --> H
    G --> H

    H{rank is not None\nand > 0?}
    H -- Yes --> I["rank_norm = 1 − (log10(rank) / log10(max_expected))\nclamped to 0..1\nrank_component = rank_norm × 0.20"]
    H -- No --> J[rank_component = 0.0]

    I --> K
    J --> K

    K["composite_score =\nnlp_component\n+ backlinks_component\n+ rank_component"]

    K --> L([Store composite_score\nin DB — used as default\nsearch sort])
```

### Weights summary

| Component | Weight | Source field | Normalisation |
|-----------|--------|--------------|---------------|
| NLP quality | **50%** | `nlp_score` | Already 0–1 |
| Backlinks | **30%** | `backlinks` | `log10(n) / log10(max)`, clamped 0–1 |
| Rank | **20%** | `rank` | `1 − log10(rank)/log10(max)`, clamped 0–1 (lower rank = better) |

> `composite_score` is the **default sort** for `ddig search`.
> Use `--sort score` to sort by `nlp_score` alone.
> NLP fields are **never overwritten** once set — `composite_score` is recomputed on every upsert where `nlp_score` is already present.