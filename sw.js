// 법령 뷰어 서비스 워커: 앱 파일은 '인터넷이 되면 최신, 안 되면 저장본', 파이오다이드(큰 파일)는 한 번 받으면 저장본을 씀.
const V = "lv-7.0";
const SHELL = ["./", "index.html", "worker.js", "lawcore.py", "mobile_api.py", "manifest.webmanifest", "icon-192.png", "icon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V && k !== "lv-pyo").map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const r = e.request;
  if (r.method !== "GET") return;
  const u = new URL(r.url);
  const pyo = /pyodide/i.test(u.pathname) || u.hostname === "cdn.jsdelivr.net";
  if (pyo) {                                                    // 파이오다이드: 저장본 우선
    e.respondWith(caches.open("lv-pyo").then(async (c) => {
      const hit = await c.match(r);
      if (hit) return hit;
      const res = await fetch(r);
      if (res && res.ok) c.put(r, res.clone());
      return res;
    }));
    return;
  }
  if (u.origin !== location.origin) return;                     // 법제처·GitHub·구글 서버는 그대로 통과
  e.respondWith(fetch(r).then((res) => {                        // 앱 파일: 최신 우선, 실패(오프라인)하면 저장본
    if (res && res.ok) { const cp = res.clone(); caches.open(V).then((c) => c.put(r, cp)); }
    return res;
  }).catch(() => caches.match(r, { ignoreSearch: true }).then((m) => m || (r.mode === "navigate" ? caches.match("index.html") : Response.error()))));
});
