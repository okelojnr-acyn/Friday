/** Where the kernel is. A self-hosted Friday (deploy/compose.yml) writes
 * /config.js when its web container starts, so one image serves any
 * domain; elsewhere (Vercel, `npm run dev`) the build-time
 * VITE_KERNEL_URL applies. */
declare global {
  interface Window {
    __FRIDAY__?: { kernelUrl?: string };
  }
}

export const KERNEL_URL: string =
  (typeof window !== "undefined" && window.__FRIDAY__?.kernelUrl) ||
  import.meta.env.VITE_KERNEL_URL ||
  "http://localhost:8080";
