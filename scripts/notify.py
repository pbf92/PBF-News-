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
        today = datetime.now(timezone.utc).astimezone(PT).date().isoformat()
        try:
            latest = json.loads((ROOT / "data" / "editions" / "index.json").read_text()).get("latest")
        except (FileNotFoundError, json.JSONDecodeError):
            latest = None
        if latest == today:
            print(f"edition for {today} is present")
            return 0
        return push({"title": "PIJ didn't publish", "body": f"No edition for {today} yet. The latest is {latest}. Check the scheduled task in Claude.",
                     "url": "./", "tag": "pij-watchdog"})
    if mode == "test":
        return push({"title": "PIJ test", "body": "Push notifications are working.", "url": "./", "tag": "pij-test"})
    print(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "send"))
