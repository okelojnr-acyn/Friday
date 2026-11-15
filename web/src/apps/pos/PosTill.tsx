import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { deviceRegisterId, listRegisters, setDeviceRegisterId, type PosRegister, type PosShift } from "../../lib/posApi";
import { PosPage } from "./PosPage";
import { ChooseRegister, CloseRegister, OpenRegister } from "./PosRegisterFlow";

/** Which screen the till shows: choose this device's till (once), the
 * idle "Open register" screen, selling, or closing with a count. */
export function PosTill({ onClockOut }: { onClockOut: () => void }) {
  const { session } = useAuth();
  const [registers, setRegisters] = useState<PosRegister[] | null>(null);
  const [registerId, setRegisterId] = useState<string | null>(deviceRegisterId());
  const [shift, setShift] = useState<PosShift | null>(null);
  const [closing, setClosing] = useState(false);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);

  const load = useCallback(async () => {
    try {
      const regs = await listRegisters();
      setRegisters(regs);
      const mine = regs.find((r) => r.id === registerId && r.active);
      if (mine) {
        setShift(mine.open_shift);
      } else if (regs.filter((r) => r.active).length === 1 && !choosing) {
        // One till in the business: no question to ask.
        const only = regs.find((r) => r.active)!;
        setDeviceRegisterId(only.id);
        setRegisterId(only.id);
        setShift(only.open_shift);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach Friday. Check the connection and reload.");
    }
  }, [registerId, choosing]);

  useEffect(() => {
    load();
  }, [load]);

  const onPendingChange = useCallback((n: number) => setPending(n), []);
  const canManage = session?.role === "owner" || session?.role === "admin";

  if (error) {
    return (
      <div className="till-stage">
        <div />
        <div className="till-stage-center">
          <div className="till-panel glass">
            <div className="till-error" style={{ margin: 0 }}>{error}</div>
            <button type="button" className="till-btn primary" onClick={() => (setError(null), load())}>
              Try again
            </button>
          </div>
        </div>
        <div />
      </div>
    );
  }
  if (registers === null) {
    return (
      <div className="till-stage">
        <div />
        <div className="till-stage-center till-text">Loading the till…</div>
        <div />
      </div>
    );
  }

  const register = registers.find((r) => r.id === registerId) ?? null;
  const active = registers.filter((r) => r.active);

  // No till chosen and several to pick from (or asked to switch).
  if ((!register && active.length > 1) || choosing) {
    return (
      <ChooseRegister
        registers={registers}
        canManage={canManage}
        onChosen={(r) => {
          setDeviceRegisterId(r.id);
          setRegisterId(r.id);
          setShift(r.open_shift);
          setChoosing(false);
          setRegisters((rs) => (rs && !rs.some((x) => x.id === r.id) ? [...rs, r] : rs));
        }}
      />
    );
  }

  if (!shift) {
    return (
      <OpenRegister
        register={register}
        onOpened={(s) => {
          setShift(s);
          // A first open with no tills made "Main till": learn its id.
          if (!register && s.register_id) {
            setDeviceRegisterId(s.register_id);
            setRegisterId(s.register_id);
            load();
          }
        }}
        onSwitchTill={() => setChoosing(true)}
        onClockOut={onClockOut}
      />
    );
  }

  if (closing) {
    return (
      <CloseRegister
        register={register}
        shift={shift}
        pendingSales={pending}
        onCancel={() => setClosing(false)}
        onClosed={() => {
          setClosing(false);
          setShift(null);
          load();
        }}
      />
    );
  }

  return (
    <PosPage
      register={register}
      shift={shift}
      onCloseRegister={() => setClosing(true)}
      onSwitchTill={() => setChoosing(true)}
      onClockOut={onClockOut}
      onPendingChange={onPendingChange}
    />
  );
}
