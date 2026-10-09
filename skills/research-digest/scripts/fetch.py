#!/usr/bin/env python3
"""Deterministic source-gathering for the research-digest skill.

Pulls arXiv (API) and blog/RSS feeds, filters to a lookback window, routes items
to topics by keyword, drops anything already seen, and prints one JSON blob on
stdout. Judgment -- what matters, how to summarize -- is Claude's job, not this
script's.

Standard library only. No pip install, so cron and sandboxed runs work as-is.

Usage:
  python3 scripts/fetch.py                          # full run, JSON to stdout
  python3 scripts/fetch.py --days 14                # override lookback
  python3 scripts/fetch.py --topic "Agents and tool use"   # one topic (repeatable)
  python3 scripts/fetch.py --no-dedup               # ignore state/seen.json
  python3 scripts/fetch.py --mark-seen              # record this run's items as seen
  python3 scripts/fetch.py --validate-feeds         # check feed URLs, then exit
  python3 scripts/fetch.py --out digest-raw.json    # also write to a file
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_AGENT = "research-digest-skill/1.0 (+https://claude.ai/code; contact: local user)"
ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_DELAY_SEC = 3.0  # arXiv API terms ask for >=3s between requests
HTTP_TIMEOUT = 30

ATOM = "{http://www.w3.org/2005/Atom}"


# ---------------------------------------------------------------- http

def http_get(url, retries=2):
    """GET a URL, transparently handling gzip. Returns bytes."""
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as exc:  # noqa: BLE001 - surfaced in the errors list
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


# ---------------------------------------------------------------- dates

def parse_date(text):
    """Parse RFC-822 or ISO-8601 into an aware UTC datetime, or None."""
    if not text:
        return None
    text = text.strip()
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    iso = text.replace("Z", "+00:00")
    for candidate in (iso, iso[:19], iso[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- text

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text, limit=1200):
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    )
    text = WS_RE.sub(" ", text).strip()
    return text[:limit]


_KW_RE = {}


def kw_pattern(kw):
    """Word-boundary matcher for a keyword. Plain substring matching is wrong for
    short acronyms: 'RAG' matches 'sto-rag-e', 'OCR' matches 'dem-ocr-acy'."""
    rx = _KW_RE.get(kw)
    if rx is None:
        # Spaces and hyphens are interchangeable, so "long context" also matches
        # "long-context" and "multi-agent" also matches "multi agent".
        core = r"[\s\-]+".join(re.escape(part) for part in re.split(r"[\s\-]+", kw) if part)
        rx = _KW_RE[kw] = re.compile(r"(?<![A-Za-z0-9])" + core + r"(?![A-Za-z0-9])", re.I)
    return rx


def keyword_score(title, body, topic):
    """Distinct keyword hits, title weighted 3x. Ranking signal, not a filter."""
    score = 0
    hits = []
    for kw in topic.get("keywords", []):
        rx = kw_pattern(kw)
        if rx.search(title or ""):
            score += 3
            hits.append(kw)
        elif rx.search(body or ""):
            score += 1
            hits.append(kw)
    return score, hits


def matching_topics(text, topics):
    """Return names of every topic whose keywords appear in text."""
    hits = []
    for topic in topics:
        for kw in topic.get("keywords", []):
            if kw_pattern(kw).search(text):
                hits.append(topic["name"])
                break
    return hits


# ---------------------------------------------------------------- arxiv

def arxiv_search_query(topic):
    cats = topic.get("arxiv_categories") or []
    kws = topic.get("keywords") or []
    parts = []
    if cats:
        parts.append("(" + " OR ".join(f"cat:{c}" for c in cats) + ")")
    if kws:
        # ti:/abs: not all: -- all: searches full text, so a generic keyword like
        # "inference" drags in every paper that says the word once in passing.
        terms = []
        for k in kws:
            q = f'"{k}"' if " " in k else k
            terms.append(f"ti:{q}")
            terms.append(f"abs:{q}")
        parts.append("(" + " OR ".join(terms) + ")")
    return " AND ".join(parts) if parts else "all:machine learning"


def fetch_arxiv(topic, cutoff, max_results, errors):
    query = arxiv_search_query(topic)
    url = ARXIV_API + "?" + urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    try:
        root = ET.fromstring(http_get(url))
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": f"arxiv:{topic['name']}", "error": f"{type(exc).__name__}: {exc}"})
        return []

    items = []
    for entry in root.findall(f"{ATOM}entry"):
        published = parse_date((entry.findtext(f"{ATOM}published") or ""))
        updated = parse_date((entry.findtext(f"{ATOM}updated") or ""))
        stamp = published or updated
        if stamp is None or stamp < cutoff:
            continue
        abs_url = (entry.findtext(f"{ATOM}id") or "").strip()
        arxiv_id = abs_url.rsplit("/", 1)[-1]
        pdf_url = ""
        for link in entry.findall(f"{ATOM}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        authors = [
            (a.findtext(f"{ATOM}name") or "").strip()
            for a in entry.findall(f"{ATOM}author")
        ]
        cats = [c.get("term") for c in entry.findall(f"{ATOM}category") if c.get("term")]
        title = clean(entry.findtext(f"{ATOM}title"), 400)
        abstract = clean(entry.findtext(f"{ATOM}summary"), 1600)
        score, hits = keyword_score(title, abstract, topic)
        items.append(
            {
                "id": f"arxiv:{arxiv_id}",
                "source_type": "arxiv",
                "source": "arXiv",
                "title": title,
                "url": abs_url,
                "pdf_url": pdf_url,
                "published": stamp.isoformat(),
                "is_revision": bool(published and updated and updated > published),
                "authors": authors[:8],
                "author_count": len(authors),
                "categories": cats[:6],
                "abstract": abstract,
                "topics": [topic["name"]],
                "score": score,
                "matched_keywords": hits[:6],
            }
        )
    return items


# ---------------------------------------------------------------- feeds

def parse_feed(raw, feed_name):
    """Parse RSS 2.0 or Atom into a list of dicts. Raises on unparseable XML."""
    root = ET.fromstring(raw)
    out = []

    # RSS 2.0 / RDF
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue
        def txt(tag):
            for child in item:
                if child.tag.split("}")[-1] == tag:
                    return child.text or ""
            return ""
        date = txt("pubDate") or txt("date") or txt("published") or txt("updated")
        out.append(
            {
                "title": clean(txt("title"), 400),
                "url": (txt("link") or txt("guid")).strip(),
                "published": parse_date(date),
                "summary": clean(txt("description") or txt("encoded") or txt("summary")),
                "source": feed_name,
            }
        )
    if out:
        return out

    # Atom
    for entry in root.findall(f"{ATOM}entry"):
        link = ""
        for cand in entry.findall(f"{ATOM}link"):
            rel = cand.get("rel", "alternate")
            if rel == "alternate" or not link:
                link = cand.get("href", "") or link
        date = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")
        body = entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content") or ""
        out.append(
            {
                "title": clean(entry.findtext(f"{ATOM}title"), 400),
                "url": link.strip(),
                "published": parse_date(date),
                "summary": clean(body),
                "source": feed_name,
            }
        )
    return out


def canonical_id(url, title):
    base = (url or "").split("?")[0].split("#")[0].rstrip("/").lower()
    if base:
        return "url:" + base
    return "title:" + re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")


def fetch_feeds(feeds, cutoff, topics, errors):
    items = []
    for feed in feeds:
        name, url = feed.get("name", feed.get("url", "?")), feed.get("url")
        if not url:
            continue
        try:
            entries = parse_feed(http_get(url), name)
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": f"feed:{name}", "url": url, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not entries:
            errors.append({"source": f"feed:{name}", "url": url, "error": "parsed 0 entries (unrecognized feed shape?)"})
            continue
        for entry in entries:
            stamp = entry["published"]
            if stamp is None or stamp < cutoff:
                continue
            hits = matching_topics(entry["title"] + " " + entry["summary"], topics)
            best = 0
            matched_kw = []
            for topic in topics:
                sc, kws = keyword_score(entry["title"], entry["summary"], topic)
                if sc > best:
                    best, matched_kw = sc, kws
            items.append(
                {
                    "id": canonical_id(entry["url"], entry["title"]),
                    "source_type": "blog",
                    "source": name,
                    "title": entry["title"],
                    "url": entry["url"],
                    "published": stamp.isoformat(),
                    "summary": entry["summary"],
                    "topics": hits,
                    "score": best,
                    "matched_keywords": matched_kw[:6],
                }
            )
    return items


# ---------------------------------------------------------------- dedup state

def load_seen(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_seen(path, seen, new_ids, expire_days, now):
    cutoff = (now - timedelta(days=expire_days)).isoformat()
    merged = {k: v for k, v in seen.items() if v >= cutoff}
    stamp = now.isoformat()
    for item_id in new_ids:
        merged.setdefault(item_id, stamp)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=1, sort_keys=True)
    return len(merged)


# ---------------------------------------------------------------- suggestions

STOPWORDS = set(
    """a an the of for and or with without via using use toward towards on in to from by
    is are be can via new novel our we this that these those it its as at into over under
    more most less better best how what why when where which through against between about
    large small does do not no than then them they their you your""".split()
)


def suggest_terms(items, topics, limit=12):
    """Recurring bigrams in items that matched no topic -- candidate new topics."""
    known = {kw.lower() for t in topics for kw in t.get("keywords", [])}
    counts = Counter()
    for item in items:
        if item.get("topics"):
            continue
        words = re.findall(r"[a-z][a-z0-9\-]+", item["title"].lower())
        words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        for a, b in zip(words, words[1:]):
            phrase = f"{a} {b}"
            if phrase not in known:
                counts[phrase] += 1
    return [{"term": t, "count": c} for t, c in counts.most_common(limit) if c >= 2]


# ---------------------------------------------------------------- main

def validate_feeds(config):
    feeds = config["sources"]["blogs"]["feeds"]
    ok, bad = [], []
    for feed in feeds:
        try:
            entries = parse_feed(http_get(feed["url"], retries=1), feed["name"])
            if entries:
                newest = max((e["published"] for e in entries if e["published"]), default=None)
                ok.append((feed["name"], len(entries), newest.date().isoformat() if newest else "no dates"))
            else:
                bad.append((feed["name"], feed["url"], "0 entries parsed"))
        except Exception as exc:  # noqa: BLE001
            bad.append((feed["name"], feed["url"], f"{type(exc).__name__}: {exc}"))
    print(f"OK ({len(ok)}):")
    for name, n, newest in ok:
        print(f"  {name:24s} {n:3d} entries, newest {newest}")
    print(f"\nFAILED ({len(bad)}):")
    for name, url, err in bad:
        print(f"  {name:24s} {url}\n      {err}")
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="Gather arXiv + blog items for the research digest.")
    ap.add_argument("--config", default=os.path.join(SKILL_DIR, "config.json"))
    ap.add_argument("--days", type=int, help="override config lookback_days")
    ap.add_argument("--topic", action="append", help="restrict to this topic name (repeatable)")
    ap.add_argument("--no-dedup", action="store_true", help="do not filter against seen state")
    ap.add_argument("--mark-seen", action="store_true",
                    help="record the returned candidate pools in the seen state")
    ap.add_argument("--also-mark", action="append", default=[], metavar="ID",
                    help="additionally mark this item id seen (repeatable) -- use for "
                         "unrouted items you pulled into the digest by hand")
    ap.add_argument("--validate-feeds", action="store_true", help="check every feed URL and exit")
    ap.add_argument("--out", help="also write the JSON to this path")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    if args.validate_feeds:
        return validate_feeds(config)

    now = datetime.now(timezone.utc)
    days = args.days or config.get("lookback_days", 7)
    cutoff = now - timedelta(days=days)

    topics = config.get("topics", [])
    if args.topic:
        wanted = {t.lower() for t in args.topic}
        topics = [t for t in topics if t["name"].lower() in wanted]
        if not topics:
            print(f"No topic matched {args.topic}. Available: "
                  f"{[t['name'] for t in config.get('topics', [])]}", file=sys.stderr)
            return 2

    errors = []
    items = []

    arxiv_cfg = config["sources"].get("arxiv", {})
    if arxiv_cfg.get("enabled", True):
        for i, topic in enumerate(topics):
            if i:
                time.sleep(ARXIV_DELAY_SEC)
            items.extend(fetch_arxiv(topic, cutoff, arxiv_cfg.get("max_results_per_topic", 60), errors))

    blogs_cfg = config["sources"].get("blogs", {})
    if blogs_cfg.get("enabled", True):
        items.extend(fetch_feeds(blogs_cfg.get("feeds", []), cutoff, topics, errors))

    # Merge duplicate arXiv hits across topics.
    merged = {}
    for item in items:
        existing = merged.get(item["id"])
        if existing:
            existing["topics"] = sorted(set(existing["topics"]) | set(item["topics"]))
        else:
            merged[item["id"]] = item
    items = list(merged.values())

    suggestions = suggest_terms(items, config.get("topics", []))

    dedup_cfg = config.get("dedup", {})
    state_path = os.path.join(SKILL_DIR, dedup_cfg.get("state_file", "state/seen.json"))
    seen = load_seen(state_path) if dedup_cfg.get("enabled", True) and not args.no_dedup else {}
    fresh = [i for i in items if i["id"] not in seen]
    suppressed = len(items) - len(fresh)

    # Blogs outrank papers at equal score: a written-up result beats a preprint.
    fresh.sort(
        key=lambda i: (i.get("score", 0) + (2 if i["source_type"] == "blog" else 0), i["published"]),
        reverse=True,
    )

    # Reserve pool slots for blogs. arXiv out-publishes every blog combined, so a
    # straight score sort buries industry write-ups under a wall of preprints.
    by_topic = {}
    pool = config.get("candidate_pool_per_topic", 25)
    for topic in topics:
        picks = [i for i in fresh if topic["name"] in i["topics"]]
        blogs = [i for i in picks if i["source_type"] == "blog"][: max(1, pool // 2)]
        papers = [i for i in picks if i["source_type"] != "blog"][: pool - len(blogs)]
        by_topic[topic["name"]] = sorted(
            blogs + papers,
            key=lambda i: (i.get("score", 0), i["published"]),
            reverse=True,
        )
    unrouted = [i for i in fresh if not i["topics"]]

    seen_total = None
    if args.mark_seen:
        # Mark only what was actually handed over: the candidate pools, plus any
        # ids named explicitly. Marking every fetched item would let a --topic run
        # suppress blog posts the other topics never got the chance to show.
        marked = {i["id"] for items in by_topic.values() for i in items}
        marked.update(args.also_mark)
        seen_total = save_seen(
            state_path, seen, sorted(marked),
            dedup_cfg.get("expire_days", 180), now,
        )

    payload = {
        "generated_at": now.isoformat(),
        "window_days": days,
        "window_start": cutoff.isoformat(),
        "topics_queried": [t["name"] for t in topics],
        "digest_target_per_topic": config.get("max_items_per_topic", 12),
        "_note": "by_topic is a ranked CANDIDATE POOL, not the digest. Select down to digest_target_per_topic using judgment; score is a crude keyword count, not a quality measure.",
        "stats": {
            "fetched": len(items),
            "new": len(fresh),
            "suppressed_as_seen": suppressed,
            "arxiv": sum(1 for i in fresh if i["source_type"] == "arxiv"),
            "blog": sum(1 for i in fresh if i["source_type"] == "blog"),
            "unrouted": len(unrouted),
            "seen_state_size": seen_total,
            "marked_seen": bool(args.mark_seen),
            "marked_count": (
                len({i["id"] for items in by_topic.values() for i in items} | set(args.also_mark))
                if args.mark_seen else 0
            ),
        },
        "by_topic": by_topic,
        "unrouted": unrouted[:25],
        "suggested_terms": suggestions,
        "errors": errors,
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
