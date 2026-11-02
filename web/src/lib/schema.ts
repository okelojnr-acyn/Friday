import { api } from "./api";
import type { ResourceSpec } from "./types";

export const fetchSchema = (app: string) => api.get<ResourceSpec[]>(`/api/${app}/schema`);
