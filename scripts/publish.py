#!/usr/bin/env python3
"""Validate and publish an edition (or a midday update) written by the editor.

usage:
  python scripts/publish.py morning   reads data/work/edition.json
  python scripts/publish.py midday    reads data/work/update.json

Writes data/editions/<date>.json, data/editions/index.json, data/threads.json,
data/state.json and prints PUSH: lines for the phone notification.
Exits 1 with a list of problems if the edition is malformed; fix and rerun.
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ED = DATA / "editions"
PT = ZoneInfo("America/Los_Angeles")
DESK_STATUS = {"story", "quiet", "failed"}
CONFIDENCE = {"confirmed", "reported", "claim", "official data", "rumour"}
THREAD_STATUS = {"new", "changed", "no_change"}


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def check_story(s, where, errs):
    for k in ("headline", "why", "sources"):
        if not s.get(k):
            errs.append(f"{where}: missing {k}")
    if len(s.get("headline", "")) > 140:
        errs.append(f"{where}: headline over 140 chars")
    for src in s.get("sources", []):
        if not str(src.get("url", "")).startswith("http"):
            errs.append(f"{where}: source without a real url ({src.get('name')})")
    weak = ("aggregator", "unconfirmed", "tip-off", "tip off")
    srcs = s.get("sources", [])
    if srcs and all(any(w in str(x.get("name", "")).lower() for w in weak) for x in srcs):
        errs.append(f"{where}: only tip-off/aggregator sources. Confirm with a core source, or move it to the desk note")
    if s.get("confidence") and s["confidence"] not in CONFIDENCE:
        errs.append(f"{where}: confidence must be one of {sorted(CONFIDENCE)}")
    th = s.get("thread")
    if th:
        if not th.get("id") or not th.get("name"):
            errs.append(f"{where}: thread needs id and name")
        if th.get("status") not in THREAD_STATUS:
            errs.append(f"{where}: thread.status must be new|changed|no_change")


def validate(ed):
    errs = []
    for k in ("date", "type", "desks"):
        if k not in ed:
            errs.append(f"edition: missing {k}")
    if len(ed.get("top", [])) > 3:
        errs.append("edition: top holds at most 3 stories")
    for i, s in enumerate(ed.get("top", [])):
        check_story(s, f"top[{i}]", errs)
    for d in ed.get("desks", []):
        if d.get("status") not in DESK_STATUS:
            errs.append(f"desk {d.get('id')}: status must be story|quiet|failed")
        if d.get("status") == "story" and not d.get("stories"):
            errs.append(f"desk {d.get('id')}: status story but no stories")
        if d.get("status") in ("quiet", "failed") and not d.get("note"):
            errs.append(f"desk {d.get('id')}: quiet/failed desks need a one-line note")
        for i, s in enumerate(d.get("stories", [])):
            check_story(s, f"desk {d.get('id')}[{i}]", errs)
    return errs


def update_threads(stories, today, close_ids):
    store = load(DATA / "threads.json", {"threads": []})
    by_id = {t["id"]: t for t in store["threads"]}
    for s in stories:
        th = s.get("thread")
        if not th:
            continue
        t = by_id.get(th["id"])
        if not t:
            t = {"id": th["id"], "name": th["name"], "desk": s.get("desk", "world"),
                 "started": today, "status": "active"}
            store["threads"].append(t)
            by_id[th["id"]] = t
        t["status"] = "active"
        if th["status"] in ("new", "changed"):
            t["last_changed"] = today
        t["last_line"] = s.get("why", "")[:200]
        t["last_seen"] = today
    for t in store["threads"]:
        started = date.fromisoformat(t["started"])
        t["day"] = (date.fromisoformat(today) - started).days + 1
        idle = (date.fromisoformat(today) - date.fromisoformat(t.get("last_changed", t["started"]))).days
        if t["id"] in close_ids or idle > 10:
            t["status"] = "closed"
    (DATA / "threads.json").write_text(json.dumps(store, indent=1, ensure_ascii=False))
    return {t["id"]: t for t in store["threads"]}


def all_stories(ed):
    out = list(ed.get("top", []))
    for d in ed.get("desks", []):
        for s in d.get("stories", []):
            s.setdefault("desk", d.get("id"))
            out.append(s)
    out.extend(ed.get("updates", []))
    return out


def write_index():
    eds = sorted((p for p in ED.glob("20*.json")), reverse=True)
    index = []
    for p in eds:
        e = load(p, {})
        index.append({"date": e.get("date"), "type": e.get("type"),
                      "top": [s["headline"] for s in e.get("top", [])][:3],
                      "status": e.get("status"), "updates": len(e.get("updates", []))})
    (ED / "index.json").write_text(json.dumps({"latest": index[0]["date"] if index else None,
                                               "editions": index}, indent=1, ensure_ascii=False))


def main(mode):
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now.astimezone(PT).date().isoformat()
    state = load(DATA / "state.json", {})
    ED.mkdir(parents=True, exist_ok=True)

    if mode == "morning":
        ed = load(DATA / "work" / "edition.json", None)
        if ed is None:
            print("ERROR: data/work/edition.json missing or not valid JSON")
            return 1
        errs = validate(ed)
        if errs:
            print("EDITION INVALID:\n- " + "\n- ".join(errs))
            return 1
        ed["generated_at"] = stamp
        ed.setdefault("updates", [])
        desks = ed["desks"]
        ed["status"] = {k: sum(1 for d in desks if d["status"] == k) for k in ("story", "quiet", "failed")}
        threads = update_threads(all_stories(ed), ed["date"], set(ed.get("close_threads", [])))
        for s in all_stories(ed):  # stamp the day count so the app can show "Day 5"
            if s.get("thread") and s["thread"]["id"] in threads:
                s["thread"]["day"] = threads[s["thread"]["id"]]["day"]
        (ED / f"{ed['date']}.json").write_text(json.dumps(ed, indent=1, ensure_ascii=False))
        state.update({"last_morning_at": stamp, "last_edition_at": stamp, "last_date": ed["date"]})
        heads = [s["headline"] for s in ed.get("top", [])][:3]
        print("PUSH_TITLE: PIJ · " + datetime.fromisoformat(ed["date"]).strftime("%a %-d %b"))
        print("PUSH_BODY: " + (" · ".join(heads) if heads else "Quiet morning — nothing cleared the bar."))
    else:
        up = load(DATA / "work" / "update.json", None)
        if up is None:
            print("ERROR: data/work/update.json missing or not valid JSON")
            return 1
        stories = up.get("updates", [])
        errs = []
        for i, s in enumerate(stories):
            check_story(s, f"update[{i}]", errs)
        if errs:
            print("UPDATE INVALID:\n- " + "\n- ".join(errs))
            return 1
        if not stories:
            print("NO_UPDATE")
            state["last_midday_at"] = stamp
            (DATA / "state.json").write_text(json.dumps(state, indent=1))
            return 0
        path = ED / f"{state.get('last_date', today)}.json"
        ed = load(path, None)
        if ed is None:
            print(f"ERROR: no edition at {path} to attach the update to")
            return 1
        local = now.astimezone(PT).strftime("%-I:%M %p")
        for s in stories:
            s["time"] = local
        ed.setdefault("updates", []).extend(stories)
        threads = update_threads(stories, today, set())
        for s in stories:
            if s.get("thread") and s["thread"]["id"] in threads:
                s["thread"]["day"] = threads[s["thread"]["id"]]["day"]
        path.write_text(json.dumps(ed, indent=1, ensure_ascii=False))
        state.update({"last_edition_at": stamp, "last_midday_at": stamp})
        for s in stories:
            print(f"PUSH_TITLE: PIJ update · {local}")
            print(f"PUSH_BODY: {s['headline']}")
    (DATA / "state.json").write_text(json.dumps(state, indent=1))
    write_index()
    print("PUBLISHED_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "morning"))
