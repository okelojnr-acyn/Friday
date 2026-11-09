import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../lib/auth";
import { LoginPage } from "../../shell/LoginPage";
import { RequirePosAuth } from "./PosClockIn";

/** POS's own trimmed route tree -- mirrors web/src/minions/MinionsApp.tsx:
 * reuses LoginPage and AuthProvider completely unchanged (same kernel,
 * same passwordless auth, same session storage), but has exactly one
 * real page. No nav bar, no other routes -- a register isn't a
 * multi-page app. RequirePosAuth (PosClockIn.tsx) is both the auth gate
 * *and* the biometric cashier clock-in gate in front of PosPage; see
 * that file for why those are one gate, not two. */
export default function PosApp() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequirePosAuth />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
