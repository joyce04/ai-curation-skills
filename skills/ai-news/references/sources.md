# Sources

Reference for `config.json`. Every source below was verified live with
`scripts/fetch_news.py --validate`. Re-run after any edit.

## Hacker News — Algolia API

`https://hn.algolia.com/api/v1/search` with
`numericFilters=created_at_i>{ts},points>{min_points}`. Free, no key, no
rate-limit problems in practice.

One query per term in `queries`, deduplicated by story id. `min_points` is the
main noise dial:

| Threshold | Effect |
| --- | --- |
| 50 | includes undiscussed submissions; noisy |
| **100** (default) | stories that actually got traction |
| 300 | only the week's biggest threads; may return very little |

High points with high comments often means a headline people reacted to without
reading — treat comment-to-point ratio as a controversy signal, not a quality one.

## Hugging Face — trending models

`https://huggingface.co/api/models?sort=trendingScore`. Free, no key.

Filtered to models whose `createdAt` falls inside the window. Without that filter
the same long-running favorites trend for weeks and every digest reports them as
new. `min_likes` (default 40) removes the long tail.

Expect quantizations and re-uploads of the same base model to occupy several
slots — GGUF, MLX, abliterated variants. Collapse them into one item.

## Hugging Face — daily papers

`https://huggingface.co/api/daily_papers`. Free, no key. Community-upvoted, so
it surfaces *buzz* rather than volume — the complement to research-digest's
exhaustive arXiv sweep. `min_upvotes` default 20. Each item carries both the HF
discussion page and the arXiv link.

## GitHub releases

`https://github.com/{owner}/{repo}/releases.atom`. No key, no auth.

`max_per_repo` (default 2) is essential: llama.cpp tags several nightly builds a
day and would otherwise be the entire release section. Each item carries
`releases_in_window`, so "10 releases this week" can be the item instead of ten
separate bullets.

Default repos: vLLM, llama.cpp, Ollama, transformers, LangGraph, MCP servers.
Replace with what your team actually depends on — that is what makes this section
worth reading.

## Newsletters

| Feed | Shape |
| --- | --- |
| TLDR AI | daily, headline-per-line, product-heavy |
| Latent Space | AINews daily roundups plus long interview posts |
| Import AI | weekly, policy and safety leaning |
| Interconnects | irregular, opinionated post-training and open-model analysis |

These are already curated, which cuts both ways: high signal, but you are
reporting someone else's picks. Prefer them as corroboration — a story appearing
in two newsletters *and* on HN is the week's real story — rather than as items in
their own right.

## Sources with no usable API or feed

Do not try to add these as feeds. Reach them by web search if a story warrants:

- **X / Twitter** — API is paid. Site-scoped search has no recency filter; a test
  search returned results months outside the window.
- **Threads** — the official API only covers posts you publish yourself.
- **DeepLearning.AI (The Batch)** — no RSS at any standard path, and the listing
  page is JS-rendered with no article links or embedded JSON in the initial HTML,
  so it cannot be parsed statically either.
- **Reddit** — `/.rss` works but rate-limits aggressively: six requests in a row
  returned `429`, and it stayed limited even throttled to one request per three
  seconds, clearing only after ~60 seconds of backoff. Usable only with long
  sleeps or a registered Reddit OAuth app. Deliberately left out.

## State

`state/seen.json` maps item id → first-seen timestamp. Ids are prefixed by type:
`hn:`, `hfmodel:`, `hfpaper:`, `gh:`, `url:`. Entries older than
`dedup.expire_days` (90, shorter than research-digest's 180 because news goes
stale faster) are pruned on each `--mark-seen`. Delete the file to reset.
