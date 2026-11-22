import { api, LONG } from "./api";
import type { AppCatalogEntry } from "./types";

export const fetchCatalog = () => api.cached<AppCatalogEntry[]>("/orgs/apps", LONG);
export const installApp = (name: string) => api.post<void>(`/orgs/apps/${name}/install`);
export const uninstallApp = (name: string) => api.del<void>(`/orgs/apps/${name}/install`);
