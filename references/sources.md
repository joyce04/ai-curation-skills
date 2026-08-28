# Sources

Reference for `config.json`. Every feed below was verified live with
`scripts/fetch.py --validate-feeds`. Re-run that after any edit.

## arXiv

Queried through the official API (`export.arxiv.org/api/query`), one request per
topic, 3s apart per arXiv's terms. Queries are built as:

```
(cat:<c1> OR cat:<c2>) AND (ti:"kw" OR abs:"kw" OR ti:kw2 OR abs:kw2 ...)
```

Title and abstract only — **never `all:`**, which searches full text and drags in
every paper that mentions a word once in passing.

Useful categories: `cs.CL` (NLP/LLMs), `cs.LG` (ML), `cs.AI`, `cs.IR`
(retrieval), `cs.DC` (distributed), `cs.PF` (performance), `cs.SE` (software
eng), `cs.CV` (vision), `cs.CR` (security), `stat.ML`.

Results are sorted by submission date; the window filter uses the v1 submission
date, so a revised older paper does not resurface. `is_revision: true` marks
papers whose latest version is newer than v1.

Volume warning: these four topics pull ~200 papers/week. The pool is capped and
ranked; the flood is mostly narrow domain applications (medical, legal, finance).
That is what the selection step in SKILL.md exists to filter.

## Blog feeds

Labs and research:

| Source | Good for |
| --- | --- |
| OpenAI | Model and product announcements, occasional research notes |
| Google DeepMind | Research announcements, model releases |
| Google Research | Broad research write-ups across ML and systems |
| Google AI | Product-leaning AI posts from the main Google blog |
| Meta Engineering | Infra at scale, some ML systems |
| Hugging Face | Practitioner-level model, training, and library write-ups. High volume |
| BAIR (Berkeley) | Academic write-ups of Berkeley work. Low volume, high quality |
| Lil'Log (Lilian Weng) | Deep survey posts. Rare, worth reading whenever it fires |
| Sebastian Raschka | LLM training and architecture explainers |
| Simon Willison | LLM tooling, releases, and practical findings. Very high volume, includes short link posts |

Engineering:

| Source | Good for |
| --- | --- |
| Cloudflare | Networking, edge, performance, incident write-ups |
| Netflix Tech | Data platform, streaming infra, ML platform |
| GitHub Engineering | Developer tooling, scale, availability |
| Stripe | Payments infra, reliability, API design |
| Slack Engineering | Backend scale, mobile, developer experience |
| Dropbox Tech | Storage, sync, infra migrations |
| Discord Engineering | Realtime systems, storage at scale |
| Databricks | Data + ML platform, Spark, warehousing |
| Jane Street | OCaml, systems, trading infra. Deep and idiosyncratic |
| Pragmatic Engineer | Industry analysis and engineering practice |

### Sources with no usable feed

Do not re-add these as feeds; they 404. Reach them via web search if a topic
warrants it:

- **Anthropic** (`anthropic.com/news`, `anthropic.com/research`) — no RSS
- **Uber Engineering** — the old `eng.uber.com/feed/` is dead; current blog serves no feed
- **Pinecone**, **Figma**, **LinkedIn Engineering** — no working feed found
- **Vercel** — `vercel.com/atom` works but is a product changelog (~1500 entries
  of "now available"). Removed deliberately: it floods routing and poisons the
  term suggestions. Re-add only if you want product-release tracking.

### Adding a feed

```json
{"name": "Short Name", "url": "https://example.com/feed.xml"}
```

Common paths to try: `/feed`, `/rss`, `/feed.xml`, `/rss.xml`, `/atom.xml`,
`/index.xml`, `/blog/feed`. Substack is always `<domain>/feed`. Then validate.

The parser handles RSS 2.0, RDF, and Atom, and decompresses gzip. It does not
handle JSON Feed or paginated feeds.

## Social (X / Threads)

**Not handled by `fetch.py`.** X's API is paid; Threads' API only covers posts
you publish yourself. The skill gathers these with site-scoped web search
instead, which means:

- coverage is partial and non-reproducible between runs
- there is no reliable timestamp filter, so recency must be judged from content
- results skew toward whatever is indexed, not what is best

Treat social as a pointer to a primary source, not a source. If a post claims a
result, find the paper or repo and cite that instead. Set
`sources.social.enabled: false` to skip it entirely.

`sources.social.accounts_of_interest` is an optional list of handles to search
alongside topic keywords (`from:handle` on x.com), for people whose posting you
specifically want to track.

## State

`state/seen.json` maps item id → first-seen timestamp. Ids are `arxiv:<id>` for
papers and `url:<canonical url>` for posts. Only ids that reached a candidate
pool are written, plus anything passed to `--also-mark`; items fetched but never
routed to a queried topic stay unseen, so a single-topic run cannot starve the
other topics. Entries older than
`dedup.expire_days` are pruned on each `--mark-seen` write. Delete the file to
reset; use `--no-dedup` for a one-off run that ignores it.
