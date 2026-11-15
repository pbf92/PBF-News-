/* PIJ app: renders data/editions/*.json as a broadsheet. No framework. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const DESK_ORDER = ["united", "world", "prop", "tradetech", "ai", "business", "faith", "health", "gaming", "expand"];
  const SHORT = { united: "United", world: "World", prop: "Prop firms", tradetech: "Trading tech", ai: "AI",
    business: "Business", faith: "Faith", health: "Health", gaming: "Gaming", expand: "Expand", markets: "Markets" };
  const state = { index: null, current: null, edition: null, open: new Set(), stripNote: null };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : null);
  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  async function getJSON(path) {
    const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }

  function fmtDate(iso, opts) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("en-GB", opts);
  }

  function badgeFor(s) {
    const t = s.thread;
    if (!t) return s.impact === "high" ? "Major" : "New";
    if (t.status === "new") return "New thread";
    return `Day ${t.day ?? "?"} · changed`;
  }

  function storyHTML(s, key, opts = {}) {
    const isOpen = state.open.has(key);
    const desk = opts.deskLabel ?? SHORT[s.desk] ?? "";
    const tags = [];
    if (s.next) tags.push(`<span class="tag outline">Next: ${esc(s.next)}</span>`);
    if (s.grade) tags.push(`<span class="tag">Evidence ${esc(s.grade)}</span>`);
    if (s.region) tags.push(`<span class="tag">${esc(s.region)}</span>`);
    if (s.confidence && s.confidence !== "confirmed" && s.confidence !== "official data")
      tags.push(`<span class="tag claim">${esc(s.confidence)}</span>`);
    let more = "";
    if (isOpen) {
      const pts = (s.points || []).map((p) => `<li>${esc(p)}</li>`).join("");
      const persp = (s.perspectives || []).length
        ? `<div class="persp">${s.perspectives.map((p) => `<div class="${p.side === "R" ? "R" : "L"}"><b>${esc(p.outlet)}</b> (${p.side === "R" ? "right" : "left"}): ${esc(p.line)}${safeUrl(p.url) ? ` <a href="${safeUrl(p.url)}" target="_blank" rel="noopener">read</a>` : ""}</div>`).join("")}</div>` : "";
      const study = s.study ? `<div class="meta"><b>Study:</b> ${esc(s.study)}</div>` : "";
      const srcs = (s.sources || []).map((x) => safeUrl(x.url)
        ? `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a>` : esc(x.name)).join("");
      more = `<div class="more">${pts ? `<ul>${pts}</ul>` : ""}${study}${persp}
        <div class="srcs"><span>Sources:</span>${srcs}</div></div>`;
    }
    return `<article class="story ${opts.lead ? "lead" : ""} ${opts.update ? "update" : ""}" id="s-${esc(key)}">
      <button class="story-btn" data-key="${esc(key)}" aria-expanded="${isOpen}">
        <span class="kicker"><span class="desk">${esc(opts.update ? s.time : desk)}</span><span class="badge">${esc(badgeFor(s))}</span></span>
        <span class="headline">${esc(s.headline)}</span>
        <span class="why">${esc(s.why)}</span>
        ${tags.length ? `<span class="tags">${tags.join("")}</span>` : ""}
      </button>${more}</article>`;
  }

  function render() {
    const e = state.edition;
    const app = $("#app");
    if (!e) {
      app.innerHTML = `<div class="empty">No edition yet.<br>The first paper lands at 5:20 AM.</div>`;
      return;
    }
    const desks = DESK_ORDER.map((id) => (e.desks || []).find((d) => d.id === id)).filter(Boolean);
    const st = e.status || {};
    const dateline = fmtDate(e.date, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const edLabel = e.type === "weekend" ? "Weekend edition" : "Morning edition";
    let html = `<header class="masthead">
      <span class="dateline">${esc(dateline)} · ${edLabel}${e.test ? " · Test" : ""}</span>
      <h1>Personal Intelligence Journal</h1>
      <div class="statusline"><span>${st.story ?? 0} ${st.story === 1 ? "desk" : "desks"} filed</span><span>${st.quiet ?? 0} quiet</span>
        ${st.failed ? `<span class="bad">${st.failed} failed</span>` : ""}<span>${e.read_minutes ?? 3} min read</span></div>
    </header>`;

    html += `<nav class="strip" aria-label="Desk status">${desks.map((d) => `<button class="chip ${d.status === "failed" ? "failed" : ""}" data-desk="${esc(d.id)}"><span class="dot st-${esc(d.status)}"></span>${esc(SHORT[d.id] || d.name)}</button>`).join("")}</nav>`;
    if (state.stripNote) {
      const d = desks.find((x) => x.id === state.stripNote);
      if (d) html += `<div class="strip-note"><b>${esc(SHORT[d.id])}:</b> ${esc(d.status === "story" ? `${(d.stories || []).length || "Lead"} ${(d.stories || []).length === 1 ? "story" : "stories"} below.` : d.note)}</div>`;
    }
    if (e.note) html += `<div class="note">${esc(e.note)}</div>`;

    (e.updates || []).slice().reverse().forEach((s, i) => { html += storyHTML(s, `u${i}`, { update: true }); });

    if ((e.before_open || []).length) {
      html += `<section class="box" aria-label="Before the open"><span class="box-title">Before the open</span>${e.before_open.map((b) => `<div class="box-row"><span class="box-time">${esc(b.time)}</span><span class="box-what">${safeUrl(b.url) ? `<a href="${safeUrl(b.url)}" target="_blank" rel="noopener">${esc(b.what)}</a>` : esc(b.what)}${b.detail ? `<small>${esc(b.detail)}</small>` : ""}</span></div>`).join("")}</section>`;
    }
    if ((e.week_ahead || []).length) {
      html += `<section class="box" aria-label="Week ahead"><span class="box-title">Week ahead</span>${e.week_ahead.map((b) => `<div class="box-row"><span class="box-time wk">${esc(b.when)}</span><span class="box-what">${safeUrl(b.url) ? `<a href="${safeUrl(b.url)}" target="_blank" rel="noopener">${esc(b.what)}</a>` : esc(b.what)}</span></div>`).join("")}</section>`;
    }

    if ((e.top || []).length) {
      html += `<div class="section-label red">Top ${e.top.length === 1 ? "story" : "stories"}</div>`;
      e.top.forEach((s, i) => { html += storyHTML(s, `t${i}`, { lead: i === 0 }); });
    }

    const withStories = desks.filter((d) => (d.stories || []).length && d.id !== "expand");
    if (withStories.length) {
      html += `<div class="section-label">The desks · tap to open</div>`;
      withStories.forEach((d) => d.stories.forEach((s, i) => {
        html += storyHTML({ ...s, desk: d.id }, `${d.id}${i}`);
      }));
    }

    const expand = e.expand || (desks.find((d) => d.id === "expand")?.stories || [])[0];
    if (expand) {
      html += `<div class="section-label">Expand my world</div>`;
      html += storyHTML({ ...expand, desk: "expand" }, "x0", { deskLabel: "Discovery" });
    }

    if ((e.watching || []).length) {
      const threads = state.threads || {};
      html += `<section class="watch"><div class="section-label" style="padding-top:12px">Still watching</div>${e.watching.map((w) => {
        const t = threads[w.thread];
        return `<div class="watch-item"><b>${esc(t ? t.name : w.thread)}</b>${t && t.day ? ` <span style="color:var(--muted);font-size:12px">· day ${t.day}</span>` : ""} — ${esc(w.line)}</div>`;
      }).join("")}</section>`;
    }

    if ((e.source_candidates || []).length) {
      html += `<section class="watch"><div class="section-label" style="padding-top:12px">Source candidates · fortnightly</div>${e.source_candidates.map((c) => `<div class="watch-item"><b>${esc(c.outlet)}</b> <span style="color:var(--muted);font-size:12px">· ${esc(SHORT[c.desk] || c.desk)} · ${esc(c.lean)} · ${esc(c.verdict)}</span><br>${esc(c.why)} <span style="color:var(--muted);font-size:12px">(${esc(c.seen)})</span></div>`).join("")}<div class="why" style="font-size:12.5px;padding-top:4px">To add one, tell Claude: "add &lt;outlet&gt; to PIJ sources".</div></section>`;
    }

    const gen = e.generated_at ? new Date(e.generated_at).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
    html += `<footer class="footer">Published ${esc(gen)} PT${(e.updates || []).length ? ` · ${e.updates.length} update(s)` : ""}<br>Facts from wires &amp; official sources · perspectives paired left &amp; right</footer>`;
    app.innerHTML = html;
  }

  function renderArchive() {
    const list = (state.index?.editions || []).map((x) => `<button class="arch ${x.date === state.current ? "current" : ""}" data-date="${esc(x.date)}">
      <span class="d">${esc(fmtDate(x.date, { weekday: "short", day: "numeric", month: "short" }))}${x.type === "weekend" ? " · weekend" : ""}</span>
      <span class="h">${esc((x.top || [])[0] || "Quiet edition")}</span></button>`).join("");
    $("#archive-list").innerHTML = list || `<p class="why">No past editions yet.</p>`;
  }

  async function loadEdition(date, { keepOpen = false } = {}) {
    try {
      state.edition = await getJSON(`data/editions/${date}.json`);
      state.current = date;
      if (!keepOpen) state.open.clear();
      state.stripNote = null;
      store.set("pij:last", date);
      history.replaceState(null, "", `#${date}`);
      render(); renderArchive();
      window.scrollTo(0, 0);
    } catch (err) {
      toast("Couldn't load that edition. Offline?");
    }
  }

  async function refresh(silent) {
    try {
      const [index, threads] = await Promise.all([getJSON("data/editions/index.json"), getJSON("data/threads.json").catch(() => ({ threads: [] }))]);
      state.threads = Object.fromEntries((threads.threads || []).map((t) => [t.id, t]));
      const newer = !state.index || index.latest !== state.index.latest;
      state.index = index;
      const hashDate = location.hash.match(/\d{4}-\d{2}-\d{2}/)?.[0];
      const target = !state.current ? (hashDate || index.latest) : (newer ? index.latest : state.current);
      if (target) await loadEdition(target, { keepOpen: !newer && !!state.current });
      else render();
      if (silent && newer && state.current) toast("New edition loaded");
    } catch (err) {
      if (!silent) toast("Offline — showing the saved paper");
      if (!state.edition) render();
    }
  }

  let toastTimer;
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }

  function step(dir) {
    const eds = state.index?.editions || [];
    const i = eds.findIndex((x) => x.date === state.current);
    const next = eds[i + dir];
    if (next) loadEdition(next.date); else toast(dir > 0 ? "That's the oldest edition" : "You're on the latest");
  }

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".story-btn");
    if (btn) {
      const k = btn.dataset.key;
      state.open.has(k) ? state.open.delete(k) : state.open.add(k);
      render();
      return;
    }
    const chip = ev.target.closest(".chip");
    if (chip) { state.stripNote = state.stripNote === chip.dataset.desk ? null : chip.dataset.desk; render(); return; }
    const arch = ev.target.closest(".arch");
    if (arch) { document.body.classList.remove("open"); loadEdition(arch.dataset.date); return; }
    if (ev.target.closest("#archive-btn")) { renderArchive(); document.body.classList.add("open"); return; }
    if (ev.target.closest(".drawer-bg") || ev.target.closest("#close-btn")) { document.body.classList.remove("open"); return; }
    if (ev.target.closest("#refresh-btn")) { refresh(false).then(() => toast("Up to date")); }
  });

  // swipe left = older edition, swipe right = newer
  let sx = null, sy = null;
  document.addEventListener("touchstart", (e) => { if (e.touches.length === 1) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; } }, { passive: true });
  document.addEventListener("touchend", (e) => {
    if (sx === null || document.body.classList.contains("open")) return;
    const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
    sx = null;
    if (Math.abs(dx) > 80 && Math.abs(dx) > Math.abs(dy) * 2) step(dx < 0 ? 1 : -1);
  }, { passive: true });

  // ---- push notifications ----
  function b64ToBytes(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  function showCode(sub) {
    $("#notif-json").value = JSON.stringify(sub);
    $("#notif-code").hidden = false;
  }
  async function notifInit() {
    const status = $("#notif-status"), btn = $("#notif-btn");
    const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      status.textContent = standalone ? "This device doesn't support web push." :
        "Add PIJ to your Home Screen (Share → Add to Home Screen), then open it from the icon to turn on notifications.";
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub && Notification.permission === "granted") {
      status.textContent = "On. Morning headlines and breaking updates arrive here.";
      btn.textContent = "Show setup code again"; btn.hidden = false;
      btn.onclick = () => showCode(sub);
    } else {
      status.textContent = "Off. Turn on to get the morning headlines and breaking updates.";
      btn.hidden = false;
      btn.onclick = async () => {
        try {
          const perm = await Notification.requestPermission();
          if (perm !== "granted") { status.textContent = "Notifications were not allowed. You can allow them in iPhone Settings → Notifications → PIJ."; return; }
          const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(window.PIJ_VAPID) });
          status.textContent = "On. One last step below.";
          showCode(s);
        } catch (err) { status.textContent = "Couldn't turn on notifications: " + err.message; }
      };
    }
  }
  document.addEventListener("click", async (ev) => {
    if (!ev.target.closest("#notif-copy")) return;
    const v = $("#notif-json").value;
    try { await navigator.clipboard.writeText(v); toast("Copied"); }
    catch { $("#notif-json").select(); toast("Select all and copy"); }
  });

  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").then(() => notifInit()).catch(() => {});
  else notifInit();
  refresh(false);
})();
