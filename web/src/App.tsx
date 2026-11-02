import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { RequireAuth } from "./shell/Layout";
import { LoginPage } from "./shell/LoginPage";
import { RegisterPage } from "./shell/RegisterPage";
import { DashboardPage } from "./shell/DashboardPage";
import { AppsCatalogPage } from "./shell/AppsCatalogPage";
import { IntegrationsSettingsPage } from "./shell/IntegrationsSettingsPage";
import { ResourcePage, AppIndexRedirect } from "./shell/ResourcePage";
import { PosPage } from "./apps/pos/PosPage";
import { TreasuryPage } from "./apps/web3/TreasuryPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/apps" element={<AppsCatalogPage />} />
          <Route path="/settings/integrations" element={<IntegrationsSettingsPage />} />
          <Route path="/pos" element={<PosPage />} />
          <Route path="/web3/treasury" element={<TreasuryPage />} />
          <Route path="/:app" element={<AppIndexRedirect />} />
          <Route path="/:app/:resource" element={<ResourcePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
