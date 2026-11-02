import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { RequireAuth } from "./shell/Layout";
import { LoginPage } from "./shell/LoginPage";
import { RegisterPage } from "./shell/RegisterPage";
import { DashboardPage } from "./shell/DashboardPage";
import { AppsCatalogPage } from "./shell/AppsCatalogPage";
import { ResourcePage, AppIndexRedirect } from "./shell/ResourcePage";
import { PosPage } from "./apps/pos/PosPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/apps" element={<AppsCatalogPage />} />
          <Route path="/pos" element={<PosPage />} />
          <Route path="/:app" element={<AppIndexRedirect />} />
          <Route path="/:app/:resource" element={<ResourcePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
