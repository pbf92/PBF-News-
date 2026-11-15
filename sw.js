/* PIJ service worker: app shell cache-first, editions network-first (falls back offline). */
const VERSION = "pij-v2";
const SHELL = ["./", "index.html", "app/style.css", "app/app.js", "manifest.webmanifest",
  "icons/icon-192.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  const isData = url.pathname.includes("/data/");
  const isShell = url.origin === location.origin && !isData;
  const key = url.origin + url.pathname; // ignore cache-busting query
  if (isData) {
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(VERSION).then((c) => c.put(key, copy)); }
      return r;
    }).catch(() => caches.match(key)));
  } else if (isShell || url.hostname.includes("fonts.")) {
    // stale-while-revalidate: instant from cache, refreshed in the background
    e.respondWith(caches.match(e.request).then((hit) => {
      const net = fetch(e.request).then((r) => {
        if (r.ok || r.type === "opaque") { const copy = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copy)); }
        return r;
      }).catch(() => hit);
      return hit || net;
    }));
  }
});

/* Push notifications sent by the free GitHub "Push notifications" workflow. */
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: "PIJ", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "PIJ", {
    body: d.body || "", tag: d.tag || "pij", icon: "icons/icon-192.png", badge: "icons/icon-192.png",
    data: { url: d.url || "./" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = new URL(e.notification.data?.url || "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) { if ("focus" in w) { w.navigate(target); return w.focus(); } }
    return self.clients.openWindow(target);
  }));
});
