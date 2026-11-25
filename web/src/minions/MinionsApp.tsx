import { WorkPage } from "./WorkPage";
import { AccountPage } from "../shell/AccountPage";
import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../lib/auth";
import { OrgSettingsProvider } from "../lib/orgSettings";
import { LoginPage } from "../shell/LoginPage";
import { RequireMinionsAuth } from "./MinionsLayout";
import { MyTasksPage } from "./MyTasksPage";
import { ExpenseClaimsPage } from "./ExpenseClaimsPage";
import { WalletPage } from "./WalletPage";
import { PayrollPage } from "./PayrollPage";
import { MePage } from "./MePage";
import { TeamPage } from "./TeamPage";

/** The trimmed route tree: My Tasks, Expense Claims, Wallet, Payroll --
 * employee-facing only. No /register or /join: an employee's account is
 * always created by an admin inviting them through the main Friday
 * shell, never self-signup here. Reuses LoginPage and AuthProvider
 * completely unchanged -- same kernel, same passwordless auth, same
 * session storage, so a user already logged into the main shell in the
 * same browser is effectively already logged in here too. */
export default function MinionsApp() {
  return (
    <AuthProvider>
      <OrgSettingsProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireMinionsAuth />}>
          <Route path="/" element={<MyTasksPage />} />
          <Route path="/expense-claims" element={<ExpenseClaimsPage />} />
          <Route path="/wallet" element={<WalletPage />} />
          <Route path="/payroll" element={<PayrollPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/me" element={<MePage />} />
          <Route path="/work" element={<WorkPage />} />
          <Route path="/devices" element={<AccountPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </OrgSettingsProvider>
    </AuthProvider>
  );
}
