# PBF News · Personal Intelligence Journal

Pete's morning paper. A home-screen web app fed by scheduled Claude runs.

## How it works
1. **Fetch (free, GitHub Actions):** `scripts/fetch.py` pulls headlines from every approved source in `sources.json` and keeps only new ones (`data/inbox/`).
2. **Edition (scheduled Claude run):** follows `RUNBOOK.md`. Code groups the headlines by desk (`scripts/prepare.py`), five desk workers research in parallel, and the editor writes the edition. `scripts/publish.py` validates it and updates the story threads.
3. **Publish (free, GitHub Pages):** every new edition redeploys the app (`index.html`, `app/`).

## Schedule (Pacific)
- Weekdays 5:20 AM: full edition with "Before the open".
- Weekends 5:50 AM: light edition. Sunday adds the week ahead.
- Weekdays ~12:05 PM and ~1:35 PM: midday checks. These are silent unless something clears the bar.

## Files Pete may want to edit
- `sources.json`: the approved source list.
- `EDITORIAL.md`: the rules every desk follows.

## Install on iPhone
Open the site in Safari, tap Share, then **Add to Home Screen**.
