import { api } from "./api";

export interface IntegrationCredential {
  provider: string;
  config: Record<string, unknown>;
  connected: boolean;
}

/** Talks to the kernel's own `/orgs/integrations/*` routes -- unlike
 * `resourceBasePath`, these aren't proxied to an app service, the kernel
 * serves them itself (see kernel/internal/integrations). */
export const listIntegrations = () => api.get<IntegrationCredential[]>("/orgs/integrations");

export const getIntegration = (provider: string) => api.get<IntegrationCredential>(`/orgs/integrations/${provider}`);

export const setIntegration = (provider: string, config: Record<string, unknown>) =>
  api.put<IntegrationCredential>(`/orgs/integrations/${provider}`, config);

export const deleteIntegration = (provider: string) => api.del<void>(`/orgs/integrations/${provider}`);
