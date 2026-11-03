import { api } from "./api";

export interface Member {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
}

/** Talks to the kernel's own `/orgs/members` and `/orgs/invites` routes --
 * same shape as lib/integrations.ts, the kernel serves these itself
 * (see kernel/internal/org/members.go and kernel/internal/auth/invites.go). */
export const listMembers = () => api.get<Member[]>("/orgs/members");

export const inviteMember = (email: string, role: string) => api.post<{ message: string; email: string }>("/orgs/invites", { email, role });

export const setMemberRole = (userId: string, role: string) => api.patch<void>(`/orgs/members/${userId}/role`, { role });

export const removeMember = (userId: string) => api.del<void>(`/orgs/members/${userId}`);
