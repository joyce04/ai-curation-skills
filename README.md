# research-digest

A [Claude Code](https://claude.ai/code) skill that gathers recent papers and engineering
blog posts on topics you track, and renders them as a summarized HTML digest.

The deterministic half — querying arXiv, parsing feeds, filtering to a date window,
routing items to topics, suppressing anything you have already seen — is a single
stdlib-only Python script. The judgment half — what is worth including, how to
summarize it, why it matters — is left to Claude, guided by `SKILL.md`.

## Install

```bash
git clone git@github.com:joyce04/research-digest-skill.git ~/.claude/skills/research-digest
```

No dependencies. `scripts/fetch.py` uses only the Python standard library, so it
also works from cron and in sandboxes where `pip install` is not available.

## Use

Ask in plain language — the skill's `description` triggers on phrasings like:

> what's new in agents this week · catch me up on retrieval · any interesting papers lately

Or invoke it explicitly with `/research-digest`.

To run the gathering step alone, without a model in the loop:

```bash
cd ~/.claude/skills/research-digest

python3 scripts/fetch.py --out /tmp/raw.json      # all topics, JSON to stdout
python3 scripts/fetch.py --topic "Retrieval and context"
python3 scripts/fetch.py --days 30                # wider window
python3 scripts/fetch.py --no-dedup               # ignore seen state
python3 scripts/fetch.py --validate-feeds         # check every feed URL
```

A full run takes 60–90 seconds; arXiv's terms require a 3-second gap between
queries, so wall time scales with topic count.

## Configure

Everything lives in `config.json`: topics, per-topic keywords and arXiv categories,
the feed list, lookback window, and caps. The shipped config is an example — replace
the topics with your own.

```json
{
  "name": "Agent backend latency",
  "keywords": ["inference latency", "tail latency", "TTFT", "KV cache"],
  "arxiv_categories": ["cs.DC", "cs.PF", "cs.AI", "cs.SE"]
}
```

Keywords are matched against paper titles and abstracts, and post titles and
summaries, on word boundaries — with spaces and hyphens treated as interchangeable,
so `long context` also matches "long-context". Title hits score 3, body hits 1.

**Prefer specific multi-word phrases.** A bare `inference` matches statistics papers;
`embedding` matches graph theory. This is the single biggest driver of digest quality.

After editing feeds, run `--validate-feeds`. It reports entry counts and the newest
post date per feed, which is how you spot a feed that still returns 200 but has been
dead for a year.

## How it works

1. **Fetch** — one arXiv API query per topic (title/abstract fields, never full text),
   plus every configured RSS/Atom feed.
2. **Route** — items are assigned to topics by keyword. Blog posts matching nothing land
   in an `unrouted` bucket, which Claude reviews by hand; literal matching misses plenty.
3. **Rank** — by keyword score, then recency, with pool slots reserved for blogs.
   arXiv out-publishes every blog combined, so a straight sort buries industry write-ups.
4. **Select** — `by_topic` is a *candidate pool*, not the digest. Claude cuts it down
   using judgment; `score` is a ranking hint, not a quality measure.
5. **Render** — a dated, self-contained HTML page grouped by topic, with a
   "why it matters" line per item.
6. **Remember** — `--mark-seen` records what was delivered, so next week's run does not
   repeat it.

## Deduplication

Four layers:

- **Across topics in one run** — merged on id, topics unioned.
- **Across runs** — `state/seen.json` maps id → first-seen timestamp, pruned after
  `dedup.expire_days` (default 180). Not committed; it is machine-local.
- **URL normalization** — query strings, fragments, trailing slashes and case are
  stripped. This matters more than it sounds: Medium-backed feeds append tracking
  parameters, so a post would otherwise look new on every run.
- **Semantic duplicates** — two posts covering the same release — are not caught by the
  script. That is the selection step's job.

`--mark-seen` records only the candidate pools, not everything fetched, so a
single-topic run cannot suppress items the other topics never had a chance to show.
An item rescued from `unrouted` is in no pool, so pass its id with `--also-mark`.

## Sources

arXiv via the official API, plus ~26 verified RSS/Atom feeds spanning research labs
(DeepMind, Google Research, Hugging Face, BAIR), practitioners (Simon Willison,
Sebastian Raschka, Lil'Log, Latent Space) and engineering blogs (Cloudflare, Netflix,
Stripe, Meta, Discord, Neo4j, NVIDIA).

See [references/sources.md](references/sources.md) for what each source is good for,
and for the list of notable sources that publish **no usable feed** — Anthropic, vLLM,
Baseten, Fireworks, LMSYS, LlamaIndex and Unstructured among them.

### On X and Threads

There is no free API for either. X's is paid; Threads' covers only posts you publish
yourself. The skill can fall back to site-scoped web search, but that has no reliable
recency filter and returns months-old results, so it is documented as *signal, not
source* and is off by default.

## Layout

```
SKILL.md              instructions Claude follows: workflow, selection criteria, rendering
config.json           topics, keywords, feeds, window, caps
scripts/fetch.py      arXiv + RSS gathering, routing, ranking, dedup. Stdlib only
references/sources.md per-source notes, dead-feed graveyard, arXiv category guide
state/seen.json       local run state (gitignored)
digests/              generated output (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
