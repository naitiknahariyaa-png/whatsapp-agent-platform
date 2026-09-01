import React, { createContext, useContext, useMemo, useState } from "react";
import { api, AuthState } from "./api";

const Ctx = createContext<AuthState>({
  token: null,
  email: null,
  login: async () => {},
  logout: () => {},
});

export function useAuth(): AuthState {
  return useContext(Ctx);
}

const TOKEN_KEY = "wap_token";
const EMAIL_KEY = "wap_email";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [email, setEmail] = useState<string | null>(() => localStorage.getItem(EMAIL_KEY));

  const value = useMemo<AuthState>(
    () => ({
      token,
      email,
      async login(email: string, password: string) {
        const data = await api<{ access_token: string }>("/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        localStorage.setItem(TOKEN_KEY, data.access_token);
        localStorage.setItem(EMAIL_KEY, email);
        setToken(data.access_token);
        setEmail(email);
      },
      logout() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(EMAIL_KEY);
        setToken(null);
        setEmail(null);
      },
    }),
    [token, email]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}