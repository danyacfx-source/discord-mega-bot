/* Service worker панели: кэширует только hash-статику /assets/*, иконку и манифест.
   HTML и /api/* никогда не кэшируются — в index подставляется токен, а API несёт данные. */
const CACHE = "panel-shell-v1";
const SAFE = [/^\/assets\//, /^\/icon\.svg$/, /^\/manifest\.webmanifest$/];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!SAFE.some((re) => re.test(url.pathname))) return;

  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(req);
      const refresh = fetch(req)
        .then((resp) => {
          if (resp.ok) cache.put(req, resp.clone());
          return resp;
        })
        .catch(() => hit);
      return hit || refresh;
    }),
  );
});
