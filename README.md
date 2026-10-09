# joyce-skills

Two [Claude Code](https://claude.ai/code) skills for reading the firehose so you
don't have to, packaged as one plugin.

| Skill | What it does | Output |
| --- | --- | --- |
| **`research-digest`** | Queries arXiv and ~26 engineering/research blog feeds for the topics you track, routes items to topics by keyword, suppresses what you've already seen | A dated, self-contained HTML digest with a "why it matters" line per item |
| **`ai-news`** | Sweeps Hacker News, Hugging Face trending models and daily papers, GitHub releases, and four AI newsletters | A short, Slack-ready markdown roundup, ~700 words |

They are deliberately different instruments. `research-digest` goes deep on
papers for one reader. `ai-news` is wide and shallow for a room of colleagues
with mixed ML background. Ask for depth and you want the first; ask "what should
I post to the team" and you want the second.

In both cases the deterministic half — querying, parsing, date-windowing,
routing, deduplicating — is a single stdlib-only Python script. The judgment
half — what's worth including, how to summarize it, why it matters — is left to
Claude, guided by the skill's `SKILL.md`.

No dependencies, no API keys. Both scripts use only the Python standard library,
so they also run from cron and inside sandboxes where `pip install` isn't
available.

## Install

### For yourself: symlink (recommended)

One symlink delivers both skills. A directory under `~/.claude/skills/` that
contains `.claude-plugin/plugin.json` is adopted as a plugin, and every
`skills/*/SKILL.md` inside it is discovered.

```bash
git clone git@github.com:joyce04/research-digest-skill.git ~/src/joyce-skills
ln -s ~/src/joyce-skills ~/.claude/skills/joyce-skills
```

Then run `/reload-plugins` in a session, or restart. Verify:

```bash
claude plugin list                    # joyce-skills@skills-dir ... loaded
claude plugin details joyce-skills    # Skills (2)  ai-news, research-digest
```

Name the symlink to match `plugin.json`'s `name` (`joyce-skills`) — the
directory name in `~/.claude/skills/` becomes the local half of the plugin id.

### For everyone else: marketplace

```
/plugin marketplace add joyce04/research-digest-skill
/plugin install joyce-skills@joyce04-skills
```

(The repo slug is historical — it held only `research-digest` at first.)

### Don't `plugin install` your own clone

`claude plugin install` **copies** the repo into a version-pinned cache
(`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`). For these two
skills that is actively the wrong mode:

- `state/seen.json` and the generated `digests/` / `news/` files get written
  into that cache directory, not your working tree.
- Your `config.json` edits land there too — and **both are orphaned on the next
  `plugin update`**, which installs into a new version directory.
- Edits you make in your clone don't take effect until you publish and update.

If you're the author, or you intend to edit `config.json` at all, use the
symlink. `marketplace.json` is committed for other people's benefit, not yours.

## Use

Ask in plain language — each skill's `description` triggers on natural
phrasings:

> what's new in agents this week · any interesting papers lately · catch me up on retrieval
>
> what's the AI news · what happened in AI this week · what should I post to the team

Or invoke explicitly. Installed as a plugin, the skills are namespaced by the
plugin name: `joyce-skills:research-digest` and `joyce-skills:ai-news`.

To run the gathering step alone, without a model in the loop — from each skill's
own directory:

```bash
cd skills/research-digest
python3 scripts/fetch.py --out /tmp/raw.json      # all topics
python3 scripts/fetch.py --topic "Retrieval and context"
python3 scripts/fetch.py --days 30                # wider window
python3 scripts/fetch.py --no-dedup               # ignore seen state
python3 scripts/fetch.py --validate-feeds         # check every feed URL

cd ../ai-news
python3 scripts/fetch_news.py --out /tmp/news.json
python3 scripts/fetch_news.py --days 3            # midweek check
python3 scripts/fetch_news.py --source hn --source papers
python3 scripts/fetch_news.py --validate          # check every source
```

Both scripts resolve `config.json` and `state/seen.json` from their own location
(`__file__`), not from the working directory, so an absolute invocation works
from anywhere.

A full `research-digest` run takes 60–90 seconds; arXiv's terms require a
3-second gap between queries, so wall time scales with topic count. `ai-news`
takes about 30.

## Configure

Each skill owns a `config.json` next to its `SKILL.md`. The shipped ones are
working examples — a populated config is the best documentation of what good
topics and feeds look like — but they are *examples*. Replace the topics and the
repo list with your own.

### research-digest

Topics, per-topic keywords and arXiv categories, the feed list, lookback window,
caps.

```json
{
  "name": "Agent backend latency",
  "keywords": ["inference latency", "tail latency", "TTFT", "KV cache"],
  "arxiv_categories": ["cs.DC", "cs.PF", "cs.AI", "cs.SE"]
}
```

Keywords match against paper titles and abstracts, and post titles and
summaries, on word boundaries — with spaces and hyphens interchangeable, so
`long context` also matches "long-context". Title hits score 3, body hits 1.

**Prefer specific multi-word phrases.** A bare `inference` matches statistics
papers; `embedding` matches graph theory. This is the single biggest driver of
digest quality.

### ai-news

Lookback, item cap, per-source limits and thresholds, the GitHub repo list, the
newsletter feeds. `sources.hackernews.min_points` is the main noise dial. The
shipped `github_releases.repos` list is a generic sample of popular AI infra —
swap it for the repos you actually depend on.

### After editing feeds

```bash
python3 skills/research-digest/scripts/fetch.py --validate-feeds
python3 skills/ai-news/scripts/fetch_news.py --validate
```

Both report entry counts and the newest post date per source, which is how you
spot a feed that still returns 200 but has been dead for a year. A source
returning 0 over 30 days is broken, not quiet.

## How research-digest works

1. **Fetch** — one arXiv API query per topic (title/abstract fields, never full
   text), plus every configured RSS/Atom feed.
2. **Route** — items are assigned to topics by keyword. Blog posts matching
   nothing land in an `unrouted` bucket, which Claude reviews by hand; literal
   matching misses plenty.
3. **Rank** — by keyword score, then recency, with pool slots reserved for
   blogs. arXiv out-publishes every blog combined, so a straight sort buries
   industry write-ups.
4. **Select** — `by_topic` is a *candidate pool*, not the digest. Claude cuts it
   down using judgment; `score` is a ranking hint, not a quality measure.
5. **Render** — a dated, self-contained HTML page grouped by topic.
6. **Remember** — `--mark-seen` records what was delivered, so next week's run
   does not repeat it.

`ai-news` follows the same shape, with curation rules tuned for a mixed
audience: it looks for cross-source corroboration (something on HN *and* in two
newsletters *and* trending on HF is the week's real story) and for narrative arcs
rather than isolated links.

## Deduplication

Four layers:

- **Across topics in one run** — merged on id, topics unioned.
- **Across runs** — `state/seen.json` maps id → first-seen timestamp, pruned
  after `dedup.expire_days` (180 for research-digest, 90 for ai-news). Not
  committed; it is machine-local.
- **URL normalization** — query strings, fragments, trailing slashes and case
  are stripped. This matters more than it sounds: Medium-backed feeds append
  tracking parameters, so a post would otherwise look new on every run.
- **Semantic duplicates** — two posts covering the same release — are *not*
  caught by the script. That is the selection step's job.

The two skills mark seen differently, on purpose. `research-digest --mark-seen`
records only the candidate pools, so a single-topic run cannot suppress items
the other topics never had a chance to show; an item rescued from `unrouted` is
in no pool, so pass its id with `--also-mark`. `ai-news --mark-seen` records
everything fetched — the whole pool is genuinely considered each run, and news
goes stale fast.

## Sources

**research-digest** — arXiv via the official API, plus ~26 verified RSS/Atom
feeds spanning research labs (DeepMind, Google Research, Hugging Face),
practitioners (Simon Willison, Sebastian Raschka, Lil'Log, Latent Space) and
engineering blogs (Cloudflare, Netflix, Stripe, Meta, Discord, Neo4j, NVIDIA).

**ai-news** — Hacker News via the Algolia API, Hugging Face trending models and
daily papers, per-repo GitHub release Atom feeds, and four newsletters (TLDR AI,
Latent Space, Import AI, Interconnects).

Per-skill notes on what each source is good for — plus a graveyard of notable
sources that publish **no usable feed** — live in
[`skills/research-digest/references/sources.md`](skills/research-digest/references/sources.md)
and
[`skills/ai-news/references/sources.md`](skills/ai-news/references/sources.md).

### On X and Threads

There is no free API for either. X's is paid; Threads' covers only posts you
publish yourself. DeepLearning.AI's The Batch is JS-rendered with no RSS. The
skills can fall back to site-scoped web search, but that has no reliable recency
filter and returns months-old results — so it is documented as *signal, not
source of record*, labeled as unverified in the output, and never allowed to be
the only support for a claim.

## Privacy

`state/seen.json` is your reading history and the generated `digests/` and
`news/` files are your rendered reading history. All three are gitignored, and
the patterns are written to match at **any** depth — a pattern like
`state/seen.json` contains a mid-pattern slash, which anchors it to the
`.gitignore`'s own directory and would silently stop matching once the skills
moved into `skills/<name>/`. Only `state/.gitkeep` is tracked, so a fresh clone
still has the directory the scripts write into.

If you fork this, check `git check-ignore -v skills/<name>/state/seen.json`
before your first commit.

## Layout

```
.claude-plugin/
  plugin.json             makes the repo a plugin; skills/ is auto-discovered
  marketplace.json        lets others `marketplace add joyce04/research-digest-skill`
skills/
  research-digest/
    SKILL.md              workflow, selection criteria, rendering instructions
    config.json           topics, keywords, feeds, window, caps
    scripts/fetch.py      arXiv + RSS gathering, routing, ranking, dedup
    references/sources.md per-source notes, dead-feed graveyard, arXiv categories
    state/.gitkeep        seen.json lands here (gitignored)
    digests/              generated HTML output (gitignored)
  ai-news/
    SKILL.md              curation rules, Slack-safe formatting, tone
    config.json           sources, thresholds, repo list, newsletter feeds
    scripts/fetch_news.py HN + HF + GitHub + newsletter gathering, dedup
    references/sources.md per-source notes and the known-unusable list
    state/.gitkeep        seen.json lands here (gitignored)
    news/                 generated markdown output (gitignored)
```

Neither `plugin.json` nor `marketplace.json` lists the skills: `skills/*/SKILL.md`
is auto-discovered, so the manifest cannot drift out of sync with the directory.

## Scheduling

Both pair with a weekly run — use the `schedule` skill for a cloud routine, or
`loop` for in-session repetition. A Monday run pairs with the default 7-day
lookback. If you schedule daily, drop the lookback to 1–2 days or every run will
mostly report items dedup already suppressed.

## License

MIT — see [LICENSE](LICENSE).
