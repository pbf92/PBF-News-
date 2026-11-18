#!/usr/bin/env python3
"""PIJ headline fetcher. Runs free on GitHub Actions (no Claude usage).

Pulls every approved source in sources.json (RSS/Atom feeds, Google News
searches, and a few calendar pages), keeps only headlines not seen before,
and writes:

  data/inbox/rolling.json   new headlines from the last ~72h, each with first_seen
  data/inbox/health.json    per-source fetch status (so the editor knows what failed)
  data/inbox/pages/<id>.txt plain text of calendar pages (BLS / Fed)
  data/seen.json            dedupe memory (14 days)
"""
import concurrent.futures as cf
import threading
import time
import urllib.error
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INBOX = DATA / "inbox"
UA = "Mozilla/5.0 (compatible; PIJ-fetcher/1.0; personal news reader)"
TIMEOUT = 20
DEFAULT_MAX = 15
WINDOW_HOURS = 72      # how old a headline may be to enter the inbox
ROLLING_HOURS = 72     # how long a headline stays in rolling.json
SEEN_DAYS = 14

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(text, limit=300):
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    text = WS_RE.sub(" ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


_GN_LOCK = threading.Lock()
_GN_LAST = [0.0]
GN_GAP = 1.5            # seconds between Google News requests (it throttles bursts)
GN_BACKOFF = (8, 25, 60)


def gn_get(url):
    """Google News, one request at a time, politely spaced, retrying when it pushes back."""
    with _GN_LOCK:
        for attempt in range(len(GN_BACKOFF) + 1):
            wait = GN_GAP - (time.time() - _GN_LAST[0])
            if wait > 0:
                time.sleep(wait)
            try:
                return get(url)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 503) or attempt == len(GN_BACKOFF):
                    raise
                time.sleep(GN_BACKOFF[attempt])
            finally:
                _GN_LAST[0] = time.time()


def gn_url(query, hours):
    days = max(1, round(hours / 24))
    q = f"{query} when:{days}d"
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def entry_time(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def fetch_feed(src, url, kind, cutoff):
    raw = gn_get(url) if kind == "gn" else get(url)
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed ({parsed.bozo_exception.__class__.__name__})")
    items = []
    for e in parsed.entries:
        title = clean(e.get("title", ""), 240)
        if not title:
            continue
        outlet = src["name"]
        if kind == "gn":
            # Google News titles look like "Headline - Outlet"
            src_tag = e.get("source", {})
            if isinstance(src_tag, dict) and src_tag.get("title"):
                outlet = src_tag["title"]
            if " - " in title:
                head, tail = title.rsplit(" - ", 1)
                if len(tail) < 60:
                    title, outlet = head.strip(), tail.strip()
        ts = entry_time(e)
        if ts and ts < cutoff:
            continue
        items.append({
            "title": title,
            "link": e.get("link", ""),
            "outlet": outlet,
            "published": iso(ts) if ts else None,
            "summary": clean(e.get("summary", ""), 300) if kind == "feed" else "",
            "via": kind,
        })
    return items


def fetch_page(src, url):
    raw = get(url).decode("utf-8", "replace")
    raw = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    return clean(raw, 40000)


def run_source(src, cutoff, hours):
    out = {"id": src["id"], "desk": src["desk"], "items": [], "errors": [], "pages": {}}
    jobs = [(u, "feed") for u in src.get("feeds", [])] + \
           [(gn_url(q, hours), "gn") for q in src.get("gn", [])]
    for url, kind in jobs:
        try:
            out["items"].extend(fetch_feed(src, url, kind, cutoff))
        except Exception as exc:  # noqa: BLE001 - record and carry on
            out["errors"].append(f"{kind}: {exc.__class__.__name__}: {str(exc)[:120]}")
    for i, url in enumerate(src.get("pages", [])):
        try:
            out["pages"][f"{src['id']}-{i}"] = {"url": url, "text": fetch_page(src, url)}
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"page: {exc.__class__.__name__}: {str(exc)[:120]}")
    return out


DISCORD_API = "https://discord.com/api/v10"
# One channel can carry several followed feeds; route each post by who posted it.
# (words in the poster's name, desk, tier, status). Fan/gossip feeds are rumour-grade.
AUTHOR_DESKS = [
    (("muppetiers", "gossip"), "united", 3, "Unsure"),
    (("manchester united", "man utd", "man united", "manutd", "mufc"), "united", 1, "Keep"),
    (("tradingview", "quantower", "pine script"), "tradetech", 1, "Keep"),
]


def discord_get(path, token):
    req = urllib.request.Request(DISCORD_API + path, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (https://github.com/pbf92/PBF-News-, 1.0)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def fetch_discord(cutoff):
    """Read Pete's private server channels, where prop firms' announcement channels are Followed.

    Secrets: DISCORD_BOT_TOKEN, and DISCORD_CHANNELS like "123456789:prop,987654321:tradetech".
    """
    import os
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    spec = os.environ.get("DISCORD_CHANNELS", "").strip()
    out = {"id": "discord", "desk": "prop", "items": [], "errors": [], "pages": {}, "configured": bool(token and spec)}
    if not out["configured"]:
        return out
    for part in spec.split(","):
        if ":" not in part:
            continue
        cid, desk = (x.strip() for x in part.split(":", 1))
        try:
            chan = discord_get(f"/channels/{cid}", token)
            msgs = discord_get(f"/channels/{cid}/messages?limit=50", token)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"channel {cid}: {exc.__class__.__name__}: {str(exc)[:120]}")
            continue
        for m in msgs:
            if m.get("type", 0) not in (0, 19):   # skip system posts such as "X followed Y" (type 12)
                continue
            ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
            if ts < cutoff:
                continue
            parts = [m.get("content", "")]
            for emb in m.get("embeds", []):
                parts += [emb.get("title", ""), emb.get("description", "")]
            text = clean("\n".join(p for p in parts if p), 1500)
            if not text:
                continue
            author = (m.get("author") or {}).get("username", "announcement")
            low = author.lower()
            msg_desk, tier, status = desk, 1, "Keep"
            for words, d, t, st in AUTHOR_DESKS:
                if any(w in low for w in words):
                    msg_desk, tier, status = d, t, st
                    break
            first = text.split(". ")[0]
            out["items"].append({
                "uid": f"discord-{m['id']}", "desk_override": msg_desk, "tier_override": tier, "status_override": status,
                "title": clean(first, 200), "link": f"https://discord.com/channels/{chan.get('guild_id')}/{cid}/{m['id']}",
                "outlet": f"Discord · {author}", "published": iso(ts), "summary": text, "via": "discord",
            })
    return out


def key_for(item):
    if item.get("uid"):
        return item["uid"]
    basis = re.sub(r"[^a-z0-9 ]", "", item["title"].lower())
    basis = WS_RE.sub(" ", basis).strip()
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


ARTICLES = DATA / "articles"
ARTICLE_PER_DESK = 15
ARTICLE_TOTAL = 140
ARTICLE_BUDGET_S = 420   # stop enriching after 7 minutes so the paper is never late


def resolve_link(item):
    link = item.get("link", "")
    if "news.google.com" not in link:
        return link
    from googlenewsdecoder import gnewsdecoder
    with _GN_LOCK:  # same politeness as the searches
        wait = GN_GAP - (time.time() - _GN_LAST[0])
        if wait > 0:
            time.sleep(wait)
        try:
            res = gnewsdecoder(link, timeout=15)
        finally:
            _GN_LAST[0] = time.time()
    if not (res.get("status") or res.get("success")):
        raise RuntimeError(str(res.get("message", res))[:160])
    return res.get("decoded_url")


def extract_text(url):
    import trafilatura
    html_doc = get(url).decode("utf-8", "replace")
    text = trafilatura.extract(html_doc, include_comments=False, include_tables=False, favor_precision=True)
    return (text or "").strip()


def enrich_articles(items, now):
    """Save the full text of the most promising new headlines so desk workers can read and confirm them.

    Picks tier-1 first, then newest, a few per desk. Paywalled pages usually yield nothing; that is fine.
    """
    ARTICLES.mkdir(parents=True, exist_ok=True)
    for f in ARTICLES.glob("*.txt"):  # keep three days
        if f.stat().st_mtime < time.time() - 3 * 86400:
            f.unlink()
    by_desk = {}
    for i in sorted(items, key=lambda i: (i.get("tier") or 3, -(datetime.fromisoformat(i["published"].replace("Z", "+00:00")).timestamp() if i.get("published") else 0))):
        if i.get("via") == "discord" or i.get("paywall"):
            continue
        by_desk.setdefault(i["desk"], [])
        if len(by_desk[i["desk"]]) < ARTICLE_PER_DESK:
            by_desk[i["desk"]].append(i)
    picks = [i for d in by_desk.values() for i in d][:ARTICLE_TOTAL]
    for i in picks:
        i["article_tried"] = True
    start = time.time()
    resolved, errors = [], []
    direct = [i for i in picks if "news.google.com" not in i.get("link", "")]
    google = [i for i in picks if "news.google.com" in i.get("link", "")]
    for i in direct:
        i["resolved_url"] = i["link"]
        resolved.append(i)
    for i in google:  # decoding Google links is sequential and polite
        if time.time() - start > ARTICLE_BUDGET_S / 2:
            errors.append("decode time budget used up")
            break
        try:
            url = resolve_link(i)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{exc.__class__.__name__}: {exc}")
            url = None
        if url:
            i["resolved_url"] = url
            resolved.append(i)
    if errors:
        print(f"decode problems ({len(errors)}), first: {errors[0][:200]}")

    def grab(i):
        try:
            text = extract_text(i["resolved_url"])
        except Exception:  # noqa: BLE001
            return None
        if len(text) < 400:
            return None
        path = ARTICLES / f"{i['key']}.txt"
        path.write_text(f"URL: {i['resolved_url']}\nTITLE: {i['title']}\nOUTLET: {i['outlet']}\n\n{text[:12000]}")
        return i, path

    got = 0
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for res in pool.map(grab, resolved):
            if res and time.time() - start < ARTICLE_BUDGET_S:
                i, path = res
                i["article"] = str(path.relative_to(ROOT))
                got += 1
    print(f"articles: {len(picks)} picked ({len(direct)} direct, {len(google)} via Google), "
          f"{len(resolved)} links resolved, {got} full texts saved")


def track_outlets(items, now):
    """Daily tally of which outlets keep surfacing, for the bi-weekly source-candidates review."""
    path = DATA / "outlets.json"
    data = load(path, {"days": {}})
    day = now.strftime("%Y-%m-%d")
    today = data["days"].setdefault(day, {})
    for i in items:
        name = (i.get("outlet") or "").strip()
        if not name or i.get("via") == "discord":
            continue
        rec = today.setdefault(name, {"n": 0, "desks": {}, "sample": i["title"][:140]})
        rec["n"] += 1
        rec["desks"][i["desk"]] = rec["desks"].get(i["desk"], 0) + 1
    keep = sorted(data["days"])[-30:]
    data["days"] = {d: data["days"][d] for d in keep}
    path.write_text(json.dumps(data, ensure_ascii=False))


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    hours = WINDOW_HOURS
    cfg = json.loads((ROOT / "sources.json").read_text())
    now = now_utc()
    cutoff = now - timedelta(hours=hours)

    seen = load(DATA / "seen.json", {})
    seen = {k: v for k, v in seen.items()
            if datetime.fromisoformat(v.replace("Z", "+00:00")) > now - timedelta(days=SEEN_DAYS)}
    rolling = load(INBOX / "rolling.json", {"items": []})
    keep_after = now - timedelta(hours=ROLLING_HOURS)
    old_items = [i for i in rolling.get("items", [])
                 if datetime.fromisoformat(i["first_seen"].replace("Z", "+00:00")) > keep_after]

    sources = list(cfg["sources"])
    for n, t in enumerate(cfg.get("watch_topics", [])):
        sources.append({"id": f"topic-{t['desk']}-{n}", "desk": t["desk"], "name": "Topic search",
                        "tier": 2, "gn": t["gn"]})
    meta = {s["id"]: s for s in sources}

    results = []
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(run_source, s, cutoff, hours) for s in sources]
        for f in cf.as_completed(futs):
            results.append(f.result())

    failed = [r for r in results if r["errors"]]
    if len(failed) > 0.25 * len(results):
        print(f"{len(failed)}/{len(results)} sources failed; waiting 2 minutes and retrying them once")
        time.sleep(120)
        retry_ids = {r["id"] for r in failed}
        results = [r for r in results if r["id"] not in retry_ids]
        with cf.ThreadPoolExecutor(max_workers=6) as pool:
            for f in cf.as_completed([pool.submit(run_source, meta[i], cutoff, hours) for i in retry_ids]):
                results.append(f.result())

    disc = fetch_discord(cutoff)
    if disc["configured"]:
        results.append(disc)
        meta["discord"] = {"id": "discord", "desk": "prop", "name": "Discord announcements (official)", "tier": 1, "max": 40}

    new_items, health = [], []
    (INBOX / "pages").mkdir(parents=True, exist_ok=True)
    for r in sorted(results, key=lambda r: r["id"]):
        s = meta[r["id"]]
        cap = s.get("max", DEFAULT_MAX)
        fresh = 0
        for item in r["items"]:
            k = key_for(item)
            if k in seen:
                continue
            seen[k] = iso(now)
            if fresh >= cap:
                continue
            fresh += 1
            new_items.append({
                "key": k, "desk": item.pop("desk_override", r["desk"]), "source_id": r["id"], "source": s["name"],
                "tier": item.pop("tier_override", s.get("tier")), "side": s.get("side"),
                "status": item.pop("status_override", s.get("status", "Keep")),
                "paywall": s.get("paywall", False), "first_seen": iso(now), **item,
            })
        for pid, page in r["pages"].items():
            (INBOX / "pages" / f"{pid}.txt").write_text(f"URL: {page['url']}\nFETCHED: {iso(now)}\n\n{page['text']}")
        health.append({"id": r["id"], "desk": r["desk"], "ok": not r["errors"],
                       "fetched": len(r["items"]), "new": fresh, "errors": r["errors"]})

    track_outlets(new_items, now)
    # back-fill: recent headlines from earlier fetches that never got their text saved
    backfill = [i for i in old_items if not i.get("article") and not i.get("article_tried")
                and datetime.fromisoformat(i["first_seen"].replace("Z", "+00:00")) > now - timedelta(hours=24)]
    enrich_articles(new_items + backfill, now)
    all_items = old_items + new_items
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / "rolling.json").write_text(json.dumps(
        {"updated": iso(now), "count": len(all_items), "items": all_items}, indent=1, ensure_ascii=False))
    (INBOX / "health.json").write_text(json.dumps(
        {"updated": iso(now), "new_this_run": len(new_items),
         "failed_sources": [h["id"] for h in health if not h["ok"]], "sources": health}, indent=1))
    (DATA / "seen.json").write_text(json.dumps(seen, indent=0, sort_keys=True))
    failed = sum(1 for h in health if not h["ok"])
    print(f"PIJ fetch: {len(new_items)} new headlines, {len(all_items)} in rolling inbox, "
          f"{failed}/{len(health)} sources with errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
