// rx service worker: app shell offline, map tiles cached as you view them.
const SHELL = "rx-shell-v4", TILES = "rx-tiles-v1", MAX_TILES = 3000;
const SHELL_URLS = ["/m", "/static/style.css", "/static/m.css", "/static/common.js", "/static/forms.js", "/static/m.js", "/static/visit.js", "/static/icon-192.png",
  "/static/vendor/leaflet/leaflet.css", "/static/vendor/leaflet/leaflet.js"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_URLS)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api/")) return;   // plan data is kept by the page itself
  if (/arcgisonline|openstreetmap/.test(u.host)) {
    e.respondWith(caches.open(TILES).then(async (c) => {
      const hit = await c.match(e.request); if (hit) return hit;
      const r = await fetch(e.request); if (r.ok || r.type === "opaque") { c.put(e.request, r.clone()); trim(c); } return r;
    }));
    return;
  }
  e.respondWith(fetch(e.request).then((r) => { if (r.ok && (u.origin === location.origin )) caches.open(SHELL).then((c) => c.put(e.request, r.clone())); return r; })
    .catch(() => caches.match(e.request).then((m) => m || caches.match("/m"))));
});
async function trim(c) { const k = await c.keys(); for (let i = 0; i < k.length - MAX_TILES; i++) await c.delete(k[i]); }
