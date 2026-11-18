# PIJ edition runbook

You are a scheduled run producing Pete's Personal Intelligence Journal. Pete is
not watching: never stop to ask a question. Make the reasonable call, note it in
the edition, and finish. All times are Pacific (America/Los_Angeles).

**Never use WebFetch or any tool that opens a web page**, and never tell a
worker to. Each new site would wait for Pete's approval, and he is not there to
give it. Articles are read from the text GitHub saved (`article` fields in the
briefs); everything else is checked with WebSearch.

The prompt that started you says which job: **morning** (weekday full edition),
**weekend** (light edition; Sunday adds the week ahead) or **midday** (update
check). Run everything from the repo root.

---------------------------------------------------------------------------
## Morning and weekend editions

### 1. Get fresh headlines (free, runs on GitHub)
```bash
date -u +%Y-%m-%dT%H:%M:%SZ > data/requests/fetch.txt
git add data/requests/fetch.txt && git commit -qm "Request fetch" && git push -q
```
Then poll for up to 12 minutes (the fetch now reads full articles too): every 30 s run `git pull -q --rebase` and check
whether `data/inbox/health.json` → `updated` is later than the time you wrote.
If it never updates, carry on with the inbox you have and set the edition
`note` to "Headline fetch was late; desks leaned on web search."

### 2. Build the desk briefs (code does the triage, no model cost)
```bash
python3 scripts/prepare.py morning
```

### 3. Research the desks in parallel
Launch **all five** desk workers in one message with the Agent tool,
`model: "sonnet"`, `run_in_background: false`. Each prompt is the text of
`prompts/desk_worker.md` with `{MODE}`, `{DATE_PT}` and `{GROUP}` filled in.
Groups: `g1-united-gaming`, `g2-world-markets`, `g3-prop-tradetech`,
`g4-ai-business`, `g5-faith-health-expand`.

Each worker writes `data/work/desks/<group>.json`. If a worker fails or writes
invalid JSON, relaunch it once. If it fails again, mark its desks `failed` with
a note. Never drop the edition because one group failed.

### 4. Edit (this is your job, as the top model)
Read every desk file and `EDITORIAL.md`, then write `data/work/edition.json`:

```json
{
  "date": "YYYY-MM-DD (today, PT)",
  "type": "weekday | weekend",
  "read_minutes": 4,
  "note": "optional one line for anything Pete should know about this run",
  "before_open": [{"time": "5:30 AM", "what": "...", "detail": "...", "url": "..."}],
  "week_ahead": [{"when": "...", "what": "...", "url": "..."}],
  "top": [ story, story, story ],
  "desks": [
    {"id": "united", "name": "Manchester United & Football", "status": "story|quiet|failed",
     "note": "...", "stories": [ story ]}
  ],
  "watching": [{"thread": "<thread id>", "line": "..."}],
  "close_threads": ["<thread id>"],
  "expand": story or null
}
```
A `story` has the same fields the workers produce, plus `"desk": "<desk id>"`.

Editing rules:
- **Top**: the 1–3 stories that matter most to Pete today, ranked by impact.
  Fewer is fine. A story in `top` is removed from its desk's `stories`, so
  nothing appears twice. If a desk's only story moved to `top`, keep the desk's
  status as `story` with a note like "Lead story: see top."
- **Desks**: always list all 10 desks in this order: united, world, prop,
  tradetech, ai, business, faith, health, gaming, expand. `expand` holds at most
  one story and also goes in the top-level `expand` field. Each desk's `name`
  comes from `sources.json`.
- **Sanity check**: cut anything recycled from an earlier edition (check the live
  threads), anything without a real source link, and any political item that
  lacks balance. Merge duplicates across desks.
- **Before the open** (weekday only): from `g2-world-markets`. Times in PT.
  Leave it empty on weekends.
- **Week ahead**: Sundays only.
- **Source candidates** (bi-weekly: Sundays in an even ISO week, i.e. when
  `date +%V` is even): run `python3 scripts/candidates.py`. From its list pick up
  to 5 outlets genuinely worth Pete's approval (quality reporting, fills a gap,
  helps left/right balance; skip aggregators, content farms and duplicates of
  approved sources). Use at most 3 searches to check reputation and bias rating
  (AllSides / Ad Fontes where available). Add to the edition:
  `"source_candidates": [{"outlet": "...", "desk": "...", "seen": "N headlines on M days",
  "lean": "rating + who rated it, or 'unrated'", "why": "one line", "verdict": "suggest | maybe | skip"}]`.
  If nothing is worth suggesting, use an empty list. Pete approves by telling Claude.
- **Watching**: up to 5 live threads with no story today, using the workers'
  `still_watching` lines.
- **Close threads** that are over: a match played, a launch done, a vote held.
- **Weekend light edition**: same structure, but keep only stories that are
  clearly worth Pete's Sunday. `read_minutes` around 2.
- **read_minutes**: about 1 minute per 3 stories, at least 2.

### 5. Publish
```bash
python3 scripts/publish.py morning
```
If it prints `EDITION INVALID`, fix `data/work/edition.json` and rerun until it
prints `PUBLISHED_OK`. Then:
```bash
git add data && git commit -qm "Edition $(TZ=America/Los_Angeles date +%F)" && \
  (git push -q || (git pull -q --rebase && git push -q))
```
The push triggers the app's publish workflow automatically.

### 6. Notify Pete
publish.py also writes `data/push/latest.json`; committing `data` (step 5) makes
GitHub send the app's own push notification automatically. Do not send any other
notification. Your final message must be exactly:
```
<PUSH_TITLE>
<PUSH_BODY>
Open: https://pbf92.github.io/PBF-News-/
```
If the run failed before publishing, your final message starts with
`PIJ FAILED:` and says in one line what broke.

---------------------------------------------------------------------------
## Midday check

1. Request a fetch exactly as in step 1 above, and poll up to 3 minutes.
2. `python3 scripts/prepare.py midday`. It keeps only Tier 1 headlines and
   headlines touching live threads since the last edition.
3. If it prints `TOTAL_CANDIDATES=0`: write `{"updates": []}` to
   `data/work/update.json`, run `python3 scripts/publish.py midday`, commit and
   push `data/state.json`, and end with the single line `No update.`
   Do not send a notification.
4. Otherwise launch **one** worker (Agent tool, `model: "sonnet"`) with this
   task: read `EDITORIAL.md`, the **midday bar** below, and every brief in
   `data/work/briefs/`; read saved `article` files where present; use at most
   2 WebSearch calls and **never WebFetch**. Return 0–2 stories in the same story
   format as the desk worker, each with `"desk"`. Returning zero is the
   expected, normal outcome.
5. Apply the midday bar yourself, strictly, then write
   `{"updates": [ ...stories... ]}` to `data/work/update.json` and run
   `python3 scripts/publish.py midday`. Commit and push `data`.
### The midday bar (a push interrupts Pete at work: be stingy)
A midday update is only for news that **cannot wait for tomorrow's paper**:
- **Market-moving now**: a Fed or major data surprise, a big earnings shock
  (e.g. Nvidia after the close), a geopolitical shock that moves Nasdaq futures.
- **Official prop-firm rule change** at a watchlist firm, effective soon.
- **Major confirmed United news**: manager change, completed signing, serious
  injury to a key player. Not rumours, previews or press-conference quotes.
- **Major breaking world event**: war or major attack, leader change, election
  result, a major policy decision taking effect.
Not: incremental updates on a live thread, analysis or commentary, previews,
studies, product launches, gaming news, anything "reported" only.
At most **2 updates per check**, and if today's edition already has 2 or more
updates, only add one for something truly major. When unsure, leave it for the
morning paper.

6. If there were stories, the committed `data/push/latest.json` sends the app's
   push automatically. End with the `PUSH_` lines and `Open: https://pbf92.github.io/PBF-News-/`. If none, end with `No update.`
