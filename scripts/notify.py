#!/usr/bin/env python3
"""Send PIJ push notifications to Pete's phone (runs on GitHub Actions).

usage:
  python scripts/notify.py send       push data/push/latest.json (written by publish.py)
  python scripts/notify.py watchdog   push a warning if today's edition is missing
  python scripts/notify.py test       push a test notification

Needs two GitHub repo secrets:
  VAPID_PRIVATE_KEY   the private half of the app's push key
  PUSH_SUBSCRIPTIONS  the subscription JSON the app shows after "Turn on notifications"
                      (one object, or a JSON list of them for several devices)
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pywebpush import WebPushException, webpush

ROOT = Path(__file__).resolve().parent.parent
PT = ZoneInfo("America/Los_Angeles")
SITE = "https://pbf92.github.io/PBF-News-/"
CLAIMS = {"sub": "mailto:pij-notify@users.noreply.github.com"}


def subscriptions():
    raw = os.environ.get("PUSH_SUBSCRIPTIONS", "").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return data if isinstance(data, list) else [data]


def push(payload):
    key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    subs = subscriptions()
    if not key or not subs:
        print("Push not configured yet (VAPID_PRIVATE_KEY or PUSH_SUBSCRIPTIONS secret missing). Skipping.")
        return 0
    sent = 0
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=json.dumps(payload), vapid_private_key=key,
                    vapid_claims=dict(CLAIMS), ttl=6 * 3600)
            sent += 1
        except WebPushException as exc:
            code = getattr(exc.response, "status_code", "?")
            print(f"push failed ({code}): {str(exc)[:200]}")
            if code in (404, 410):
                print("That subscription has expired: turn notifications on again in the app and update the secret.")
    print(f"sent {sent}/{len(subs)}: {payload['title']} | {payload['body'][:80]}")
    return 0 if sent or not subs else 1


def main(mode):
    if mode == "send":
        path = ROOT / "data" / "push" / "latest.json"
        if not path.exists():
            print("no push file")
            return 0
        msgs = json.loads(path.read_text())
        rc = 0
        for m in msgs.get("messages", []):
            rc |= push({"title": m["title"], "body": m["body"], "url": m.get("url", "./"), "tag": m.get("tag", "pij")})
        return rc
    if mode == "watchdog":
        # check what the APP actually serves, not just what is in the repo
        import urllib.request
        today = datetime.now(timezone.utc).astimezone(PT).date().isoformat()
        latest = None
        try:
            with urllib.request.urlopen(f"{SITE}data/editions/index.json?t={datetime.now().timestamp()}", timeout=20) as r:
                latest = json.loads(r.read()).get("latest")
        except Exception as exc:  # noqa: BLE001
            print(f"could not read the live app: {exc}")
        if latest == today:
            print(f"app is serving today's edition ({today})")
            return 0
        try:
            in_repo = json.loads((ROOT / "data" / "editions" / "index.json").read_text()).get("latest")
        except (FileNotFoundError, json.JSONDecodeError):
            in_repo = None
        why = ("the paper was written but the app couldn't be updated" if in_repo == today
               else "no edition was written: check the scheduled task in Claude")
        return push({"title": "PIJ is late", "body": f"No edition for today in the app yet: {why}.",
                     "url": "./", "tag": "pij-watchdog"})
    if mode == "test":
        return push({"title": "PIJ test", "body": "Push notifications are working.", "url": "./", "tag": "pij-test"})
    print(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "send"))
