import { api } from "./api";

/** Phone notifications for Minions (Web Push; kernel /me/push/*). */

export type PushState = "unsupported" | "needs-install" | "blocked" | "off" | "on";

const supported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

// iPhones and iPads only allow it from the home-screen app (iOS 16.4+).
const iosBrowserTab = () =>
  /iPhone|iPad|iPod/.test(navigator.userAgent) &&
  !window.matchMedia("(display-mode: standalone)").matches &&
  !(navigator as Navigator & { standalone?: boolean }).standalone;

async function registration(): Promise<ServiceWorkerRegistration> {
  return navigator.serviceWorker.ready;
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return iosBrowserTab() ? "needs-install" : "unsupported";
  if (Notification.permission === "denied") return "blocked";
  const sub = await (await registration()).pushManager.getSubscription();
  return sub ? "on" : "off";
}

function keyBytes(base64url: string): Uint8Array {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Asks the person, subscribes this phone, and tells the kernel. */
export async function turnOnPush(): Promise<void> {
  if ((await Notification.requestPermission()) !== "granted") {
    throw new Error("Notifications are blocked for this app. Allow them in the phone's settings, then try again.");
  }
  const { public_key } = await api.get<{ public_key: string }>("/me/push/key");
  const reg = await registration();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(public_key) as BufferSource,
    });
  }
  await api.post("/me/push/subscriptions", sub.toJSON());
}

/** Stops this phone (turned off, or signing out). Best effort. */
export async function turnOffPush(): Promise<void> {
  if (!supported()) return;
  const sub = await (await registration()).pushManager.getSubscription();
  if (!sub) return;
  try {
    await api.post("/me/push/unsubscribe", { endpoint: sub.endpoint });
  } catch {
    // the kernel forgets it anyway once the push service says it's gone
  }
  await sub.unsubscribe();
}
