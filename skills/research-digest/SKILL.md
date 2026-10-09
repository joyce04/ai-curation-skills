---
name: research-digest
description: Gather recent papers (arXiv), engineering blog posts, and social chatter on the user's tracked topics and render a summarized HTML digest. Use whenever the user asks "what's new in X", "catch me up on Y", "any interesting papers this week", "research digest", "weekly digest", "what did I miss", "anything new on <topic>", "recent papers on X", "what's happening in <field>", or asks to add/remove/change digest topics or sources. Also use when a scheduled digest run fires.
---

# Research Digest

Turns tracked topics into a dated HTML digest of recent papers and blog posts.
`scripts/fetch.py` does the deterministic gathering; you do the selection, the
summarizing, and the "why this matters" judgment. Never hand-assemble a source
list the script can produce.

## Quick start

Every `scripts/...` path in this file is relative to **this skill's own
directory** — the one containing this `SKILL.md`, `config.json`, and `scripts/`.
`cd` there first. If the working directory is uncertain, call the script by its
absolute path instead: it resolves `config.json` and `state/seen.json` from its
own location rather than from the cwd, so an absolute invocation works from
anywhere.

```bash
cd /path/to/skills/research-digest                    # the dir holding this SKILL.md
python3 scripts/fetch.py --out /tmp/digest-raw.json   # stdlib only, no install
```

Then read the JSON, select the best items per topic, and render the HTML artifact.
Mark items seen **only after** the digest is delivered (step 6).

## Workflow

### 1. Check the config
`config.json` holds topics, keywords, feeds, lookback, and caps. If the user is
asking about a topic that isn't in there, ask whether to add it before running —
a one-off question ("papers on state space models?") may not deserve a permanent
topic.

### 2. Fetch
```bash
python3 scripts/fetch.py --out /tmp/digest-raw.json          # all topics
python3 scripts/fetch.py --topic "Agents and tool use"       # one topic
python3 scripts/fetch.py --days 30                           # wider window
python3 scripts/fetch.py --no-dedup                          # ignore seen state
```
Takes 30–90s (arXiv rate-limits to one request per 3s per topic). Check
`errors[]` in the output and tell the user if a source failed — a silently
missing feed reads as "nothing published this week", which is a lie.

### 3. Add social signal (optional, per `sources.social`)
There is no free API for X or Threads. Use web search scoped to those sites:

```
site:x.com <topic keywords> (past week)
site:threads.net <topic keywords>
```

Cap at `sources.social.max_items_per_topic`. Include a social item only when it
points to something substantive — a result, a write-up, a released model. Skip
opinion threads and engagement bait. Mark these clearly as social in the output;
they are lower-fidelity than arXiv and RSS and must never be the sole support
for a claim.

### 4. Select
`by_topic` is a ranked **candidate pool** (~25/topic), not the digest. Cut it to
`digest_target_per_topic` (default 12) using judgment. `score` is a keyword count
— a ranking hint, not a quality measure. Do not just take the top N by score.

Prefer:
- results over position papers; released artifacts (code, weights, benchmarks) over promises
- work that changes what someone would *do*, not just what they'd know
- one strong paper over three incremental variants of it — say "three papers this week refined X" and cover the best
- surprising or contrarian findings over confirmations

Drop:
- narrow domain applications of a known method, unless the domain is one the user tracks (medical/legal/finance RAG papers flood these queries)
- benchmark papers with no finding beyond "we made a benchmark"
- product announcements dressed as engineering posts

**Also read `unrouted[]`.** Those are blog posts that matched no keyword. Some
are relevant anyway — the script matches literal strings, you don't. Pull the
good ones into the right topic.

### 5. Render the HTML artifact
Load the `artifact-design` skill before writing the page. Then write the HTML to
`digests/digest-YYYY-MM-DD.html` and publish it with the Artifact tool.

Structure — grouped by topic, in `config.json` topic order:
- Header: date, window covered, item count, sources queried
- One section per topic. Within a topic, blogs before papers.
- Per item: **title (linked)**, source + date, a 2–3 sentence summary in plain
  language, then a `Why it matters:` line tying it to the topic. Papers get
  their authors' affiliation if notable.
- A short "Also noted" list of one-liners for items worth knowing but not
  reading — keeps the main list short without discarding coverage.
- Footer: any `errors[]`, the count suppressed as already-seen, and topic
  suggestions (step 7).

Summarize from the abstract/summary in the JSON. If an abstract is too thin to
summarize honestly, fetch the page — do not pad with plausible-sounding filler.
Never state a result the source didn't claim.

### 6. Mark seen
After the digest is delivered:
```bash
python3 scripts/fetch.py --mark-seen > /dev/null                    # all topics
python3 scripts/fetch.py --topic "X" --mark-seen \
        --also-mark url:https://example.com/post > /dev/null        # rescued item
```
This re-runs the fetch and records the ids in `state/seen.json`, so the next run
skips them. Entries expire after `dedup.expire_days` (180).

`--mark-seen` records **the candidate pools only**, not everything fetched — a
`--topic` run must not suppress blog posts the other topics never got to show.
The consequence: an item you rescued from `unrouted[]` is not in any pool, so
pass its id with `--also-mark` or it will resurface next week.

Marking before delivery risks losing items to a failed run. If the user says a
digest was useless and wants a redo, run with `--no-dedup`.

### 7. Recommend config changes
Every run, look at `suggested_terms[]` (recurring phrases from items that matched
no topic) and at `unrouted[]`, and propose concrete edits:
- a new topic, when several unrouted items cluster around one theme
- a keyword to add, when relevant work keeps being missed
- a keyword to remove, when it keeps pulling junk (generic single words are the
  usual culprit — `inference` matches statistics papers, `embedding` matches
  graph theory)
- a feed to drop, when a source contributes only noise

Propose, then apply to `config.json` if the user agrees. Keep it to 1–3
suggestions; a wall of suggestions gets ignored.

## Adding sources and topics

Edit `config.json`. Prefer specific multi-word keywords over bare words. After
adding feeds:

```bash
python3 scripts/fetch.py --validate-feeds
```

This checks every feed URL and reports entry counts and the newest post date. A
feed whose newest post is over a year old is dead — drop it. See
[references/sources.md](references/sources.md) for the current source list, what
each is good for, and notes on sources that have no usable feed.

## Scheduling

For a recurring digest, use the `schedule` skill to register a cloud routine, or
the `loop` skill for in-session repetition. A weekly Monday run pairs with the
default 7-day lookback; if you schedule daily, drop `lookback_days` to 1–2 or
every run will mostly report items dedup already suppressed.

A scheduled run should still do steps 2–7, including `--mark-seen`.
