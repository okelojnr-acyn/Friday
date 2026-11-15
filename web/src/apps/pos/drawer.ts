/** Opening the cash drawer when a cash sale is paid.
 *
 * Most drawers plug into the receipt printer (RJ11) and open on a pulse
 * the printer sends. Two ways to send it from a browser:
 *
 * - "printer": the receipt is printed, and the printer's Windows driver
 *   is set to open the drawer when it prints (Epson, Xprinter, Rongta and
 *   most ESC/POS drivers have "Cash drawer: open before printing"). No
 *   browser permission needed; this is the default.
 * - "serial": the till sends the ESC/POS drawer pulse itself over Web
 *   Serial (Chrome/Edge), for a printer or drawer that shows up as a COM
 *   port. The cashier picks the port once; Chrome remembers it.
 * - "none": no drawer; the screen still says how much change to give.
 *
 * The choice is per device (localStorage), set from the till menu. */

export type DrawerMode = "printer" | "serial" | "none";

const MODE_KEY = "friday.pos.drawer_mode";

export function drawerMode(): DrawerMode {
  try {
    const v = localStorage.getItem(MODE_KEY);
    return v === "serial" || v === "none" ? v : "printer";
  } catch {
    return "printer";
  }
}

export function setDrawerMode(mode: DrawerMode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    // ignore
  }
}

// ESC p m t1 t2: pulse drawer pin 2 for 50 ms on, 500 ms off.
const KICK = new Uint8Array([0x1b, 0x70, 0x00, 0x19, 0xfa]);

interface SerialPortLike {
  open(o: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  writable: WritableStream<Uint8Array> | null;
}
interface SerialLike {
  getPorts(): Promise<SerialPortLike[]>;
  requestPort(): Promise<SerialPortLike>;
}

function serial(): SerialLike | null {
  return (navigator as unknown as { serial?: SerialLike }).serial ?? null;
}

export function serialSupported(): boolean {
  return serial() !== null;
}

/** Asks the cashier to pick the drawer's COM port (needs a click). */
export async function chooseSerialDrawer(): Promise<void> {
  const s = serial();
  if (!s) throw new Error("This browser can't reach USB or serial devices. Use Chrome or Edge.");
  await s.requestPort();
}

/** Sends the drawer pulse over the remembered serial port. */
async function kickSerial(): Promise<void> {
  const s = serial();
  if (!s) throw new Error("This browser can't reach the drawer.");
  const [port] = await s.getPorts();
  if (!port) throw new Error("No drawer port chosen yet. Set it up from the till menu.");
  await port.open({ baudRate: 9600 }).catch((e: unknown) => {
    // Already open from an earlier kick is fine.
    if (!(e instanceof DOMException && e.name === "InvalidStateError")) throw e;
  });
  const writer = port.writable?.getWriter();
  if (!writer) throw new Error("The drawer port isn't writable.");
  try {
    await writer.write(KICK);
  } finally {
    writer.releaseLock();
  }
}

/** Opens the drawer for a cash payment. For "printer" mode the receipt
 * print does it, so this returns false and the caller prints. Returns
 * whether a pulse was sent here. Throws with a cashier-readable message. */
export async function openDrawer(): Promise<boolean> {
  const mode = drawerMode();
  if (mode === "serial") {
    await kickSerial();
    return true;
  }
  return false;
}
