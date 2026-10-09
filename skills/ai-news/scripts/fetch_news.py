#!/usr/bin/env python3
"""Source-gathering for the ai-news skill.

Pulls Hacker News (Algolia), Hugging Face trending models and daily papers,
GitHub releases, and newsletter feeds; filters to a date window; drops anything
already seen; prints one JSON blob on stdout. Claude does the curation.

Standard library only -- no pip install, so cron and sandboxed runs work as-is.

Usage:
  python3 scripts/fetch_news.py                  # full run, JSON to stdout
  python3 scripts/fetch_news.py --days 3         # tighter window
  python3 scripts/fetch_news.py --source hn      # one source (repeatable)
  python3 scripts/fetch_news.py --no-dedup       # ignore state/seen.json
  python3 scripts/fetch_news.py --mark-seen      # record this run's items
  python3 scripts/fetch_news.py --validate       # check every source, then exit
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_AGENT = "ai-news-skill/1.0 (+https://claude.ai/code)"
HTTP_TIMEOUT = 30
ATOM = "{http://www.w3.org/2005/Atom}"

HN_API = "https://hn.algolia.com/api/v1/search"
HF_MODELS = "https://huggingface.co/api/models"
HF_PAPERS = "https://huggingface.co/api/daily_papers"


# ---------------------------------------------------------------- http

def http_get(url, retries=2):
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as exc:  # noqa: BLE001 - surfaced in errors[]
            last = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


def http_json(url, retries=2):
    return json.loads(http_get(url, retries).decode("utf-8", "replace"))


# ---------------------------------------------------------------- text/date

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text, limit=800):
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(a, b)
    return WS_RE.sub(" ", text).strip()[:limit]


def parse_date(text):
    if not text:
        return None
    text = str(text).strip()
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    iso = text.replace("Z", "+00:00")
    for cand in (iso, iso[:19], iso[:10]):
        try:
            dt = datetime.fromisoformat(cand)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def canonical_id(prefix, value):
    base = (value or "").split("?")[0].split("#")[0].rstrip("/").lower()
    return f"{prefix}:{base}"


# ---------------------------------------------------------------- sources

def fetch_hn(cfg, cutoff, errors):
    """Hacker News via Algolia. Free, no key, filterable by date and points."""
    ts = int(cutoff.timestamp())
    seen, items = set(), []
    for query in cfg.get("queries", []):
        url = HN_API + "?" + urllib.parse.urlencode({
            "tags": "story",
            "numericFilters": f"created_at_i>{ts},points>{cfg.get('min_points', 100)}",
            "query": query,
            "hitsPerPage": 50,
        })
        try:
            data = http_json(url)
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": f"hn:{query}", "error": f"{type(exc).__name__}: {exc}"})
            continue
        for hit in data.get("hits", []):
            oid = hit.get("objectID")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            stamp = parse_date(hit.get("created_at"))
            if stamp is None or stamp < cutoff:
                continue
            items.append({
                "id": f"hn:{oid}",
                "source_type": "hackernews",
                "source": "Hacker News",
                "title": clean(hit.get("title"), 300),
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "discussion_url": f"https://news.ycombinator.com/item?id={oid}",
                "published": stamp.isoformat(),
                "points": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "matched_query": query,
            })
        time.sleep(0.3)  # be polite to Algolia
    items.sort(key=lambda i: i["points"], reverse=True)
    return items[: cfg.get("max_items", 25)]


def fetch_hf_models(cfg, cutoff, errors):
    """Trending models, filtered to ones CREATED in the window.

    Without the creation filter the same long-running favorites trend for weeks
    and every digest reports the same models as if they were new.
    """
    url = HF_MODELS + "?" + urllib.parse.urlencode(
        {"sort": "trendingScore", "limit": 100}
    )
    try:
        data = http_json(url)
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "hf:models", "error": f"{type(exc).__name__}: {exc}"})
        return []
    items = []
    for m in data:
        created = parse_date(m.get("createdAt"))
        if created is None or created < cutoff:
            continue
        if (m.get("likes") or 0) < cfg.get("min_likes", 40):
            continue
        mid = m.get("id") or m.get("modelId")
        items.append({
            "id": f"hfmodel:{mid}",
            "source_type": "model_release",
            "source": "Hugging Face",
            "title": mid,
            "url": f"https://huggingface.co/{mid}",
            "published": created.isoformat(),
            "likes": m.get("likes", 0),
            "downloads": m.get("downloads", 0),
            "pipeline_tag": m.get("pipeline_tag"),
            "tags": [t for t in (m.get("tags") or []) if not t.startswith("license:")][:8],
        })
    items.sort(key=lambda i: i["likes"], reverse=True)
    return items[: cfg.get("max_items", 12)]


def fetch_hf_papers(cfg, cutoff, errors):
    """HF daily papers -- community upvotes, so this surfaces buzz, not volume."""
    try:
        data = http_json(HF_PAPERS + "?limit=100")
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "hf:papers", "error": f"{type(exc).__name__}: {exc}"})
        return []
    items = []
    for entry in data:
        paper = entry.get("paper") or {}
        stamp = parse_date(entry.get("publishedAt") or paper.get("publishedAt"))
        if stamp is None or stamp < cutoff:
            continue
        up = paper.get("upvotes") or 0
        if up < cfg.get("min_upvotes", 20):
            continue
        pid = paper.get("id")
        items.append({
            "id": f"hfpaper:{pid}",
            "source_type": "paper_buzz",
            "source": "HF Daily Papers",
            "title": clean(paper.get("title") or entry.get("title"), 300),
            "url": f"https://huggingface.co/papers/{pid}",
            "arxiv_url": f"https://arxiv.org/abs/{pid}",
            "published": stamp.isoformat(),
            "upvotes": up,
            "num_comments": entry.get("numComments", 0),
            "summary": clean(paper.get("summary") or entry.get("summary"), 900),
        })
    items.sort(key=lambda i: i["upvotes"], reverse=True)
    return items[: cfg.get("max_items", 15)]


def parse_atom_entries(raw):
    root = ET.fromstring(raw)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        link = ""
        for cand in e.findall(f"{ATOM}link"):
            if cand.get("rel", "alternate") == "alternate" or not link:
                link = cand.get("href", "") or link
        out.append({
            "title": clean(e.findtext(f"{ATOM}title"), 300),
            "url": link,
            "date": parse_date(e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published")),
            "body": clean(e.findtext(f"{ATOM}content") or e.findtext(f"{ATOM}summary"), 700),
        })
    return out


def fetch_github(cfg, cutoff, errors):
    # Per-repo cap: llama.cpp alone tags several nightly builds a day and would
    # otherwise be the entire release section.
    per_repo = cfg.get("max_per_repo", 2)
    items = []
    for repo in cfg.get("repos", []):
        repo_items = []
        try:
            entries = parse_atom_entries(http_get(f"https://github.com/{repo}/releases.atom"))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": f"gh:{repo}", "error": f"{type(exc).__name__}: {exc}"})
            continue
        for e in entries:
            if e["date"] is None or e["date"] < cutoff:
                continue
            repo_items.append({
                "id": canonical_id("gh", e["url"]),
                "source_type": "release",
                "source": repo,
                "title": f"{repo} {e['title']}",
                "url": e["url"],
                "published": e["date"].isoformat(),
                "notes": e["body"],
                "releases_in_window": 0,
            })
        repo_items.sort(key=lambda i: i["published"], reverse=True)
        for it in repo_items[:per_repo]:
            it["releases_in_window"] = len(repo_items)
            items.append(it)
        time.sleep(0.2)
    items.sort(key=lambda i: i["published"], reverse=True)
    return items


def parse_feed(raw, name):
    """RSS 2.0 / RDF / Atom -> list of dicts."""
    root = ET.fromstring(raw)
    out = []
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue
        def txt(tag):
            for ch in item:
                if ch.tag.split("}")[-1] == tag:
                    return ch.text or ""
            return ""
        out.append({
            "title": clean(txt("title"), 300),
            "url": (txt("link") or txt("guid")).strip(),
            "date": parse_date(txt("pubDate") or txt("date") or txt("published")),
            "body": clean(txt("description") or txt("encoded") or txt("summary"), 700),
        })
    if out:
        return out
    return [{"title": e["title"], "url": e["url"], "date": e["date"], "body": e["body"]}
            for e in parse_atom_entries(raw)]


def fetch_newsletters(cfg, cutoff, errors):
    items = []
    for feed in cfg.get("feeds", []):
        name, url = feed.get("name"), feed.get("url")
        try:
            entries = parse_feed(http_get(url), name)
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": f"news:{name}", "url": url, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not entries:
            errors.append({"source": f"news:{name}", "url": url, "error": "parsed 0 entries"})
            continue
        for e in entries:
            if e["date"] is None or e["date"] < cutoff:
                continue
            items.append({
                "id": canonical_id("url", e["url"]),
                "source_type": "newsletter",
                "source": name,
                "title": e["title"],
                "url": e["url"],
                "published": e["date"].isoformat(),
                "summary": e["body"],
            })
    items.sort(key=lambda i: i["published"], reverse=True)
    return items


# ---------------------------------------------------------------- state

def load_seen(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_seen(path, seen, ids, expire_days, now):
    cutoff = (now - timedelta(days=expire_days)).isoformat()
    merged = {k: v for k, v in seen.items() if v >= cutoff}
    stamp = now.isoformat()
    for i in ids:
        merged.setdefault(i, stamp)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=1, sort_keys=True)
    return len(merged)


# ---------------------------------------------------------------- main

FETCHERS = {
    "hn": ("hackernews", fetch_hn),
    "models": ("huggingface_models", fetch_hf_models),
    "papers": ("huggingface_papers", fetch_hf_papers),
    "github": ("github_releases", fetch_github),
    "newsletters": ("newsletters", fetch_newsletters),
}


def validate(config):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    errors = []
    print("Checking every source over a 30-day window:\n")
    for key, (cfg_key, fn) in FETCHERS.items():
        cfg = config["sources"].get(cfg_key, {})
        n = len(fn(cfg, cutoff, errors))
        print(f"  {key:12s} {n:4d} items")
    print("\nERRORS:" if errors else "\nERRORS: none")
    for e in errors:
        print(f"  {e['source']}: {e['error'][:90]}")
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description="Gather AI news items.")
    ap.add_argument("--config", default=os.path.join(SKILL_DIR, "config.json"))
    ap.add_argument("--days", type=int)
    ap.add_argument("--source", action="append", choices=sorted(FETCHERS),
                    help="restrict to this source (repeatable)")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--mark-seen", action="store_true")
    ap.add_argument("--also-mark", action="append", default=[], metavar="ID")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    if args.validate:
        return validate(config)

    now = datetime.now(timezone.utc)
    days = args.days or config.get("lookback_days", 7)
    cutoff = now - timedelta(days=days)
    wanted = set(args.source or FETCHERS)

    errors, by_source = [], {}
    for key, (cfg_key, fn) in FETCHERS.items():
        cfg = config["sources"].get(cfg_key, {})
        if key not in wanted or not cfg.get("enabled", True):
            by_source[key] = []
            continue
        by_source[key] = fn(cfg, cutoff, errors)

    all_items = [i for group in by_source.values() for i in group]

    dedup = config.get("dedup", {})
    state_path = os.path.join(SKILL_DIR, dedup.get("state_file", "state/seen.json"))
    seen = load_seen(state_path) if dedup.get("enabled", True) and not args.no_dedup else {}
    fresh = [i for i in all_items if i["id"] not in seen]
    suppressed = len(all_items) - len(fresh)
    keep = {i["id"] for i in fresh}
    by_source = {k: [i for i in v if i["id"] in keep] for k, v in by_source.items()}

    seen_total = None
    if args.mark_seen:
        seen_total = save_seen(state_path, seen,
                               [i["id"] for i in fresh] + args.also_mark,
                               dedup.get("expire_days", 90), now)

    payload = {
        "generated_at": now.isoformat(),
        "window_days": days,
        "window_start": cutoff.isoformat(),
        "digest_target": config.get("max_items", 14),
        "_note": "by_source is a candidate pool, not the digest. Curate down to digest_target. "
                 "points/likes/upvotes are popularity, not quality.",
        "stats": {
            "fetched": len(all_items),
            "new": len(fresh),
            "suppressed_as_seen": suppressed,
            **{k: len(v) for k, v in by_source.items()},
            "seen_state_size": seen_total,
        },
        "by_source": by_source,
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
