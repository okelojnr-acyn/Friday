import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { RequireAuth } from "./shell/Layout";
import { LoginPage } from "./shell/LoginPage";
import { RegisterPage } from "./shell/RegisterPage";
import { AcceptInvitePage } from "./shell/AcceptInvitePage";
import { SsoLoginPage } from "./shell/SsoLoginPage";
import { DashboardPage } from "./shell/DashboardPage";
import { AppsCatalogPage } from "./shell/AppsCatalogPage";
import { IntegrationsSettingsPage } from "./shell/IntegrationsSettingsPage";
import { MembersSettingsPage } from "./shell/MembersSettingsPage";
import { ResourcePage, AppIndexRedirect } from "./shell/ResourcePage";
import { TreasuryPage } from "./apps/web3/TreasuryPage";
import { MarketPage } from "./apps/web3/MarketPage";
import { ReportsPage } from "./apps/accounting/ReportsPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/join" element={<AcceptInvitePage />} />
        <Route path="/sso" element={<SsoLoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/apps" element={<AppsCatalogPage />} />
          <Route path="/settings/integrations" element={<IntegrationsSettingsPage />} />
          <Route path="/settings/members" element={<MembersSettingsPage />} />
          {/* POS moved to its own installable mini-app (web/pos.html,
              apps/pos/PosApp.tsx) -- gated behind a biometric cashier
              clock-in that only makes sense as a dedicated entry, same
              reasoning Minions already has its own entry. Reachable from
              the dashboard tile (external link, not this route table). */}
          <Route path="/web3/treasury" element={<TreasuryPage />} />
          <Route path="/accounting/reports" element={<ReportsPage />} />
          <Route path="/web3/market" element={<MarketPage />} />
          <Route path="/:app" element={<AppIndexRedirect />} />
          <Route path="/:app/:resource" element={<ResourcePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
