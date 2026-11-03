import { useEffect } from "react";

const SCAN_KEY_GAP_MS = 60;
const SCAN_MIN_LENGTH = 6;

/** A barcode scanner is a keyboard-wedge device: it "types" a code
 * faster than any human can and ends with Enter. Timing (not focus) is
 * what tells a scan apart from someone typing elsewhere on the page --
 * works regardless of which element has focus, matching how a real
 * USB/Bluetooth scanner behaves. Originally POS register-only logic,
 * extracted here so any screen that wants scan-to-add (the bulk-add-
 * products panel included) doesn't duplicate it.
 *
 * `enabled` lets a caller pause listening (e.g. while a modal that
 * shouldn't react to scans is open) without unmounting the component. */
export function useBarcodeScanner(onScan: (code: string) => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    let buffer = "";
    let lastAt = 0;

    function onKeyDown(e: KeyboardEvent) {
      const now = performance.now();
      const gap = now - lastAt;
      lastAt = now;

      if (e.key === "Enter") {
        const code = buffer;
        buffer = "";
        if (code.length >= SCAN_MIN_LENGTH) onScan(code);
        return;
      }
      if (e.key.length === 1) {
        if (gap > SCAN_KEY_GAP_MS) buffer = "";
        buffer += e.key;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onScan, enabled]);
}
