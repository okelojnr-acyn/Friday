import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { saveSession } from "../lib/session";
import { Card } from "../ui/Card";

/** Entry point for Friday Host's admin-app SSO bridge: Friday Host
 * mints a token signed with this kernel's own JWT_SECRET (see
 * friday-cloud-labs/src/lib/api/admin-bridge.ts) and redirects the
 * browser here with it. That token is already a fully valid Friday
 * session, so there is nothing to verify client-side -- just store it
 * and go. The kernel's own API independently verifies every request's
 * token signature as usual, same as any normal login. */
export function SsoLoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = params.get("token");
    const orgId = params.get("org_id");
    const role = params.get("role");
    const email = params.get("email");
    if (!token || !orgId || !role || !email) {
      setError("Missing SSO parameters");
      return;
    }
    saveSession({ token, orgId, role: role as "owner" | "admin" | "member" | "viewer", email });
    navigate("/", { replace: true });
    // params is a new URLSearchParams instance each render; read once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!error) return null;

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
      </Card>
    </div>
  );
}
