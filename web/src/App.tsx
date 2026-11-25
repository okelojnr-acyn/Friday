import { SupplierPage } from "./shell/SupplierPage";
import { PaidPage } from "./shell/PaidPage";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { OrgSettingsProvider } from "./lib/orgSettings";
import { RequireAuth } from "./shell/Layout";
import { LoginPage } from "./shell/LoginPage";
import { RegisterPage } from "./shell/RegisterPage";
import { AcceptInvitePage } from "./shell/AcceptInvitePage";
import { SsoLoginPage } from "./shell/SsoLoginPage";
import { StepUpPage } from "./shell/StepUpPage";
import { DashboardPage } from "./shell/DashboardPage";
import { AppsIntegrationsPage } from "./shell/AppsIntegrationsPage";
import { PeoplePage } from "./shell/PeoplePage";
import { AppFrame } from "./shell/AppFrame";
import { StorePage } from "./shell/StorePage";
import { ImportPage } from "./shell/ImportPage";
import { BusinessSettingsPage } from "./shell/BusinessSettingsPage";
import { StoreSettingsPage } from "./shell/StoreSettingsPage";
import { EtimsFilingPage } from "./shell/EtimsFilingPage";
import { UnitsPage } from "./apps/inventory/UnitsPage";
import { ResourcePage, AppIndexRedirect } from "./shell/ResourcePage";
import { TreasuryPage } from "./apps/web3/TreasuryPage";
import { MarketPage } from "./apps/web3/MarketPage";
import { ReportsPage } from "./apps/accounting/ReportsPage";
import { OverviewPage as AccountingOverviewPage } from "./apps/accounting/OverviewPage";
import { PipelinePage } from "./apps/crm/PipelinePage";
import { ReceivablesPage } from "./apps/invoicing/ReceivablesPage";
import { InvoiceEditorPage } from "./apps/invoicing/InvoiceEditorPage";

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
        <Route path="/supplier" element={<SupplierPage />} />
        <Route path="/paid" element={<PaidPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/join" element={<AcceptInvitePage />} />
        <Route path="/sso" element={<SsoLoginPage />} />
        <Route path="/step-up" element={<StepUpPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/apps" element={<AppsIntegrationsPage />} />
          <Route path="/settings/integrations" element={<IntegrationsRedirect />} />
          <Route path="/store" element={<StorePage />} />
          <Route path="/settings/people" element={<Navigate to="/people" replace />} />
          <Route path="/settings/members" element={<Navigate to="/people" replace />} />
          <Route path="/settings/import" element={<ImportPage />} />
          <Route path="/settings/business" element={<BusinessSettingsPage />} />
          <Route path="/settings/store" element={<StoreSettingsPage />} />
          <Route element={<AppFrame />}>
            <Route path="/etims" element={<EtimsFilingPage />} />
            <Route path="/inventory/unit_of_measure" element={<UnitsPage />} />
            {/* POS moved to its own installable mini-app (web/pos.html,
                apps/pos/PosApp.tsx) -- gated behind a biometric cashier
                clock-in that only makes sense as a dedicated entry, same
                reasoning Minions already has its own entry. Reachable from
                the dashboard tile (external link, not this route table). */}
            <Route path="/crm" element={<PipelinePage />} />
            <Route path="/invoicing" element={<ReceivablesPage />} />
            <Route path="/invoicing/invoice/new" element={<InvoiceEditorPage />} />
            <Route path="/web3/treasury" element={<TreasuryPage />} />
            <Route path="/accounting" element={<AccountingOverviewPage />} />
            <Route path="/accounting/reports" element={<ReportsPage />} />
            <Route path="/web3/market" element={<MarketPage />} />
            {/* People is Minions' admin side (owner, 2026-11-22); /minions/ is the staff app. */}
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/people/:resource" element={<ResourcePage app="minions" />} />
            <Route path="/:app" element={<AppIndexRedirect />} />
            <Route path="/:app/:resource" element={<ResourcePage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </OrgSettingsProvider>
    </AuthProvider>
  );
}
