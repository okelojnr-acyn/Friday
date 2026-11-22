import { api, LONG } from "./api";
import type { ResourceSpec } from "./types";

export const fetchSchema = (app: string) => api.cached<ResourceSpec[]>(`/api/${app}/schema`, LONG);
