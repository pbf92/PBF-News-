#!/usr/bin/env python3
"""Turn the raw inbox into compact desk briefs for the edition run.

Doing this in code (not with a model) is the cheapest triage tier: it groups
fresh headlines by desk, drops what earlier editions already covered, caps
volume, and attaches each desk's live threads and source health.

usage: python scripts/prepare.py morning|midday
writes data/work/briefs/<group>.json and prints a summary line per group.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WORK = DATA / "work" / "briefs"

GROUPS = {
    "g1-united-gaming": ["united", "gaming"],
    "g2-world-markets": ["world", "markets"],
    "g3-prop-tradetech": ["prop", "tradetech"],
    "g4-ai-business": ["ai", "business"],
    "g5-faith-health-expand": ["faith", "health", "expand"],
}
PER_DESK_CAP = {"world": 90, "markets": 25}
DEFAULT_CAP = 45


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main(mode):
    now = datetime.now(timezone.utc)
    state = load(DATA / "state.json", {})
    inbox = load(DATA / "inbox" / "rolling.json", {"items": []})
    health = load(DATA / "inbox" / "health.json", {"sources": []})
    threads = load(DATA / "threads.json", {"threads": []})["threads"]
    sources = json.loads((ROOT / "sources.json").read_text())

    if mode == "midday":
        since = parse(state.get("last_edition_at", (now - timedelta(hours=8)).isoformat()))
    else:
        default = now - timedelta(hours=60 if now.weekday() in (0, 5, 6) else 30)
        since = parse(state.get("last_morning_at", default.isoformat()))
        since = min(since, now - timedelta(hours=20))  # always look back at least 20h

    fresh = [i for i in inbox["items"] if parse(i["first_seen"]) > since]
    if mode == "midday":
        # midday only cares about high-signal sources: tier 1, or anything touching a live thread
        live_words = {w.lower() for t in threads if t.get("status") == "active"
                      for w in t["name"].split() if len(w) > 4}
        fresh = [i for i in fresh if i.get("tier") == 1 or
                 any(w in i["title"].lower() for w in live_words)]

    WORK.mkdir(parents=True, exist_ok=True)
    total = 0
    for group, desks in GROUPS.items():
        brief = {"mode": mode, "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "desks": {}}
        for d in desks:
            items = [i for i in fresh if i["desk"] == d]
            items.sort(key=lambda i: i.get("published") or "", reverse=True)  # newest first
            items.sort(key=lambda i: i.get("tier") or 3)                       # then tier 1 first (stable)
            items = items[:PER_DESK_CAP.get(d, DEFAULT_CAP)]
            brief["desks"][d] = {
                "name": sources["desks"][d]["name"],
                "headlines": [{k: i.get(k) for k in
                               ("title", "outlet", "source", "tier", "side", "status", "paywall",
                                "published", "link", "summary")} for i in items],
                "threads": [t for t in threads if t["desk"] == d and t.get("status") == "active"],
                "sources_failed": [h["id"] for h in health.get("sources", [])
                                   if h["desk"] == d and not h["ok"]],
                "approved_sources": [{"name": s["name"], "tier": s["tier"], "side": s.get("side"),
                                      "lean": s.get("lean"), "status": s.get("status", "Keep"),
                                      "feeds": s.get("feeds", []), "pages": s.get("pages", [])}
                                     for s in sources["sources"] if s["desk"] == d],
            }
            total += len(items)
        if "markets" in desks:
            pages = DATA / "inbox" / "pages"
            brief["calendar_pages"] = {p.stem: p.read_text()[:15000] for p in sorted(pages.glob("*.txt"))} \
                if pages.exists() else {}
        (WORK / f"{group}.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False))
        counts = {d: len(brief["desks"][d]["headlines"]) for d in desks}
        print(f"{group}: {counts}")
    print(f"TOTAL_CANDIDATES={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "morning"))
