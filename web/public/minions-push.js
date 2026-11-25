/* Phone notifications for Minions (Web Push). Loaded into the Minions
 * service worker (vite.config.ts, workbox.importScripts). The kernel sends
 * {title, body, url, tag, silent}; tapping opens url in Minions. */
self.addEventListener("push", (event) => {
  let n = {};
  try {
    n = event.data ? event.data.json() : {};
  } catch (e) {
    n = { title: "Friday", body: event.data ? event.data.text() : "" };
  }
  const url = typeof n.url === "string" && n.url.startsWith("/") ? n.url : "/minions/";
  event.waitUntil(
    self.registration.showNotification(n.title || "Friday", {
      body: n.body || "",
      tag: n.tag || undefined, // a resend of the same event replaces it
      silent: Boolean(n.silent), // quiet hours: no sound
      icon: "/minions-icon-192.png",
      badge: "/minions-icon-192.png",
      data: { url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/minions/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      // Reuse an open Minions window when there is one.
      for (const w of wins) {
        if (new URL(w.url).pathname.startsWith("/minions") && "focus" in w) {
          return w.navigate(url).then((c) => (c || w).focus());
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
