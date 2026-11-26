/** A soft two-note chime for a new notice: two sine tones a fourth
 * apart (E5 then A5), gentle attack, a long fade, quiet. Made in the
 * browser, so no sound file to load. Off when the person turns it off
 * (remembered on this device). */
const KEY = "friday.sound";
let ctx: AudioContext | null = null;

export function soundOn(): boolean {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function setSound(on: boolean) {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // private window: stays on for this visit
  }
  if (on) chime();
}

export function chime() {
  if (!soundOn()) return;
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    ctx ??= new AC();
    void ctx.resume();
    const t0 = ctx.currentTime + 0.02;
    [659.25, 880].forEach((hz, i) => {
      const start = t0 + i * 0.14;
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = "sine";
      osc.frequency.value = hz;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.9);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(start);
      osc.stop(start + 1);
    });
  } catch {
    // no audio here (or not allowed before a first tap): stay quiet
  }
}
