#!/usr/bin/env python3
"""List outlets that keep surfacing in the last 14 days but are not on Pete's approved list.

Used every other Sunday for the "Source candidates" section. Prints JSON lines, busiest first.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERIC = {"youtube", "yahoo", "msn", "google", "reddit", "facebook", "x.com", "twitter", "linkedin", "medium"}


def main():
    data = json.loads((ROOT / "data" / "outlets.json").read_text()) if (ROOT / "data" / "outlets.json").exists() else {"days": {}}
    approved = [s["name"].lower() for s in json.loads((ROOT / "sources.json").read_text())["sources"]]
    days = sorted(data["days"])[-14:]
    tally = defaultdict(lambda: {"n": 0, "days": 0, "desks": defaultdict(int), "sample": ""})
    for d in days:
        for name, rec in data["days"][d].items():
            t = tally[name]
            t["n"] += rec["n"]; t["days"] += 1; t["sample"] = rec.get("sample", t["sample"])
            for desk, n in rec["desks"].items():
                t["desks"][desk] += n
    rows = []
    for name, t in tally.items():
        low = name.lower()
        if any(a in low or low in a for a in approved) or any(g in low for g in GENERIC):
            continue
        if t["n"] < 4 or t["days"] < 3:
            continue
        rows.append({"outlet": name, "headlines": t["n"], "days_seen": t["days"],
                     "desk": max(t["desks"], key=t["desks"].get), "sample": t["sample"]})
    rows.sort(key=lambda r: (-r["days_seen"], -r["headlines"]))
    print(json.dumps({"window_days": len(days), "candidates": rows[:20]}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
