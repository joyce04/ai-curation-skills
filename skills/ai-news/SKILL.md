---
name: ai-news
description: Gather the week's AI news — Hacker News discussion, trending models and papers, tool releases, and newsletter roundups — and write a short, Slack-ready markdown digest. Use whenever the user asks "what's the AI news", "what happened in AI this week", "anything big happen", "catch me up", "what should I post to the team", "AI roundup", "weekly news", "what's everyone talking about", or asks to change news sources. Lighter and newsier than the research-digest skill, which covers papers in depth.
---

# AI News

A short, forwardable roundup of what happened in AI this week, written for a
team Slack channel. `scripts/fetch_news.py` gathers; you curate and write.

**This is not research-digest.** That skill goes deep on papers for one reader.
This one is wide and shallow for a room of colleagues with mixed ML background.
If the user wants depth on a topic, use research-digest instead.

## Quick start

Every `scripts/...` path in this file is relative to **this skill's own
directory** — the one containing this `SKILL.md`, `config.json`, and `scripts/`.
`cd` there first. If the working directory is uncertain, call the script by its
absolute path instead: it resolves `config.json` and `state/seen.json` from its
own location rather than from the cwd, so an absolute invocation works from
anywhere.

```bash
cd /path/to/skills/ai-news                           # the dir holding this SKILL.md
python3 scripts/fetch_news.py --out /tmp/news.json   # stdlib only, ~30s
```

Then curate down to `digest_target` items and write the markdown.

## Workflow

### 1. Fetch
```bash
python3 scripts/fetch_news.py --out /tmp/news.json   # all sources, 7-day window
python3 scripts/fetch_news.py --days 3               # midweek check
python3 scripts/fetch_news.py --source hn --source papers
python3 scripts/fetch_news.py --validate             # check every source
```
Check `errors[]` and say so if a source failed. Five sources, none needing a key:

| Source | Signal |
| --- | --- |
| `hn` | what the industry is arguing about (points + comment counts) |
| `papers` | HF daily papers — community upvotes, so buzz not volume |
| `models` | HF trending models created inside the window |
| `github` | what actually shipped, capped per repo |
| `newsletters` | TLDR AI, Latent Space, Import AI, Interconnects |

### 2. Add search-only sources (per `sources.search_only`)
X, Threads and DeepLearning.AI's The Batch have no usable API or feed — X's API
is paid, Threads' covers only your own posts, and The Batch is JS-rendered with
no RSS. Reach them with web search:

```
site:x.com <topic> · site:threads.com <topic> · deeplearning.ai The Batch
```

Site-scoped search has **no reliable recency filter** and returns months-old
results. Include an item only if you can confirm it is inside the window and it
points at something real. Label it as unverified. Never let it be the only
support for a claim. If nothing qualifies, say so rather than padding.

### 3. Curate
`by_source` is a candidate pool, not the digest. Cut to `max_items` (14).
Points, likes and upvotes are **popularity, not quality** — a 900-point thread
is often a headline everyone reacted to without reading.

Pick for a mixed engineering audience:
- the one or two stories everybody will hear about anyway — cover them first, briefly
- anything that changes a tool, default, or API someone on the team actually uses
- one unglamorous practical result (the small model doing a boring job well)
- a skeptic or counterweight piece — a roundup of only launches reads as marketing
- security and incident stories, which travel well and are usually under-covered internally

Drop:
- vendor announcements with no artifact, benchmark, or price attached
- the fourth take on a story already covered by items one through three
- pure discourse threads with high comments and no underlying event
- models trending on HF that are quantizations or re-uploads of something already listed

**Look for the arc.** The best digest item is not one link, it is three that form
a story — a launch, its clones, and someone claiming prior art. Merge them into one
bullet rather than spending three.

**Cross-source corroboration is the quality signal.** Something that appears on
HN *and* in two newsletters *and* as a trending model is the week's real story.
Use the overlap; the script does not compute it for you.

### 4. Write it
Write to `news/news-YYYY-MM-DD.md`. Structure:

- One-sentence **TL;DR** naming the week's actual story, not a list of topics
- 4–6 themed sections, each a bold line plus 2–4 bullets
- Per item: **bold linked title**, one sentence of what happened, then a short
  italic clause on why a colleague should care. Not every item needs the clause —
  use it where it isn't obvious.
- A single "read this one" pick
- A one-line footer: item count, sources, window, any errors

Tone: plain, specific, a little dry. Assume smart readers who are not all ML
specialists. Expand an acronym on first use. No hype, no emoji-per-bullet, no
"game-changing". A section emoji or two is fine as a visual anchor.

Keep it under ~700 words — it has to survive being read in a Slack scroll.

**Slack-safe formatting.** Slack's composer converts pasted markdown, but only a
subset. Use **bold**, bullets, and `[text](url)` links. Avoid tables, nested
lists, and `#` headers — use a bold line as a section header instead. Horizontal
rules and a small `<sub>` footer survive fine in the file and degrade harmlessly.

### 5. Mark seen
After delivering:
```bash
python3 scripts/fetch_news.py --mark-seen > /dev/null
python3 scripts/fetch_news.py --mark-seen --also-mark hn:12345678   # extra ids
```
Records everything fetched this run, so next week's digest does not repeat it.
Entries expire after `dedup.expire_days` (90). Use `--no-dedup` for a redo.

Note this differs from research-digest, which marks only delivered pools. Here
the whole pool is genuinely considered each run, and news goes stale fast, so
marking everything is correct.

### 6. Suggest changes
Occasionally, not every run:
- a GitHub repo to add, when the team starts depending on it
- an HN query term to add or drop (`queries` in config) — `min_points` is the
  main noise dial, raise it if the digest feels thin on substance
- a newsletter that contributed nothing for several weeks

## Configure

`config.json`: lookback, item cap, per-source limits and thresholds, the repo
list, newsletter feeds. After editing feeds or repos:

```bash
python3 scripts/fetch_news.py --validate
```

Reports item counts per source over 30 days and any errors. A source returning 0
over 30 days is broken, not quiet. See
[references/sources.md](references/sources.md) for what each source is good for
and the known-unusable list.

## Scheduling

Pairs well with a weekly run — Monday morning for a Friday-to-Friday window, or
Friday afternoon for a post people read over the weekend. Use the `schedule`
skill. If you run it daily, set `--days 1`; the 7-day default will mostly return
items dedup already suppressed.
