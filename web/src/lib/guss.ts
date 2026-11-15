import { api } from "./api";

/** The org's Guss, reached through the kernel (kernel/internal/guss). */
export const gussStatus = () => api.get<{ connected: boolean }>("/guss/status");
export const gussChat = (text: string) => api.post<{ reply: string }>("/guss/chat", { text });
export const gussReport = (window: "day" | "week" | "month") =>
  api.get<{ reply: string }>(`/guss/report?window=${window}`);

export type GussAccessLevel = "none" | "read" | "write";

export interface GussLink {
  telegram_id: number;
  telegram_name: string;
  user_id: string;
  email: string;
  role: string;
  guss_role: string;
}

export interface GussAccess {
  access: Record<string, GussAccessLevel>;
  apps: string[];
  has_service_key: boolean;
  links: GussLink[];
}

/** What Guss may do per app, its key, and linked people
 * (kernel/internal/guss/link.go). */
export const getGussAccess = () => api.get<GussAccess>("/guss/access");
export const setGussAccess = (access: Record<string, GussAccessLevel>) =>
  api.put<{ access: Record<string, GussAccessLevel> }>("/guss/access", { access });
export const newGussServiceKey = () => api.post<{ key: string }>("/guss/service-key");
export const linkGussTelegram = (code: string) =>
  api.post<{ telegram_id: number; telegram_name: string }>("/guss/link", { code });
export const unlinkGussTelegram = (telegramId: number) => api.del<void>(`/guss/links/${telegramId}`);
