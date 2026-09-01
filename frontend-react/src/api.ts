export interface AuthState {
  token: string | null;
  email: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export async function api<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || j.error || JSON.stringify(j);
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}