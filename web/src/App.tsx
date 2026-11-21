import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { OrgSettingsProvider } from "./lib/orgSettings";
import { RequireAuth } from "./shell/Layout";
import { LoginPage } from "./shell/LoginPage";
import { RegisterPage } from "./shell/RegisterPage";
import { AcceptInvitePage } from "./shell/AcceptInvitePage";
import { SsoLoginPage } from "./shell/SsoLoginPage";
import { DashboardPage } from "./shell/DashboardPage";
import { AppsIntegrationsPage } from "./shell/AppsIntegrationsPage";
import { MembersSettingsPage } from "./shell/MembersSettingsPage";
import { ImportPage } from "./shell/ImportPage";
import { BusinessSettingsPage } from "./shell/BusinessSettingsPage";
import { EtimsFilingPage } from "./shell/EtimsFilingPage";
import { UnitsPage } from "./apps/inventory/UnitsPage";
import { ResourcePage, AppIndexRedirect } from "./shell/ResourcePage";
import { TreasuryPage } from "./apps/web3/TreasuryPage";
import { MarketPage } from "./apps/web3/MarketPage";
import { ReportsPage } from "./apps/accounting/ReportsPage";
import { PipelinePage } from "./apps/crm/PipelinePage";
import { ReceivablesPage } from "./apps/invoicing/ReceivablesPage";

// Integrations moved onto Apps & integrations; Google's OAuth callback
// still lands here, so its result rides along and opens Google Calendar.
function IntegrationsRedirect() {
  const { search } = useLocation();
  const p = new URLSearchParams(search);
  if (p.has("google_calendar")) p.set("item", "google_calendar");
  const q = p.toString();
  return <Navigate to={`/apps${q ? `?${q}` : ""}`} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <OrgSettingsProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/join" element={<AcceptInvitePage />} />
        <Route path="/sso" element={<SsoLoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/apps" element={<AppsIntegrationsPage />} />
          <Route path="/settings/integrations" element={<IntegrationsRedirect />} />
          <Route path="/settings/members" element={<MembersSettingsPage />} />
          <Route path="/settings/import" element={<ImportPage />} />
          <Route path="/settings/business" element={<BusinessSettingsPage />} />
          <Route path="/etims" element={<EtimsFilingPage />} />
          <Route path="/inventory/unit_of_measure" element={<UnitsPage />} />
          {/* POS moved to its own installable mini-app (web/pos.html,
              apps/pos/PosApp.tsx) -- gated behind a biometric cashier
              clock-in that only makes sense as a dedicated entry, same
              reasoning Minions already has its own entry. Reachable from
              the dashboard tile (external link, not this route table). */}
          <Route path="/crm" element={<PipelinePage />} />
          <Route path="/invoicing" element={<ReceivablesPage />} />
          <Route path="/web3/treasury" element={<TreasuryPage />} />
          <Route path="/accounting/reports" element={<ReportsPage />} />
          <Route path="/web3/market" element={<MarketPage />} />
          <Route path="/:app" element={<AppIndexRedirect />} />
          <Route path="/:app/:resource" element={<ResourcePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </OrgSettingsProvider>
    </AuthProvider>
  );
}
