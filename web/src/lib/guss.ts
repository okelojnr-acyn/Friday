import { api } from "./api";

/** The org's Guss, reached through the kernel (kernel/internal/guss). */
export const gussStatus = () => api.get<{ connected: boolean }>("/guss/status");
export const gussChat = (text: string) => api.post<{ reply: string }>("/guss/chat", { text });
export const gussReport = (window: "day" | "week" | "month") =>
  api.get<{ reply: string }>(`/guss/report?window=${window}`);
