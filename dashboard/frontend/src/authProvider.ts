import type { AuthProvider } from "@refinedev/core";
import { api } from "./api";

export type Identity = {
  id: string;
  username: string;
  role: "admin" | "operator" | "viewer";
  full_name?: string;
};

export const authProvider: AuthProvider = {
  login: async ({ username, password }) => {
    try {
      await api.post("/api/auth/login", { username, password });
      return { success: true, redirectTo: "/" };
    } catch (e: any) {
      return {
        success: false,
        error: {
          name: "LoginError",
          message: e?.response?.data?.detail || "Usuário ou senha inválidos",
        },
      };
    }
  },

  logout: async () => {
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* ignore — clear client state regardless */
    }
    return { success: true, redirectTo: "/login" };
  },

  check: async () => {
    try {
      await api.get("/api/auth/me");
      return { authenticated: true };
    } catch (e: any) {
      const setup = e?.response?.headers?.["x-mundix-setup"] === "required";
      return {
        authenticated: false,
        redirectTo: setup ? "/setup" : "/login",
        logout: true,
      };
    }
  },

  onError: async (error) => {
    if (error?.response?.status === 401) {
      return { logout: true, redirectTo: "/login" };
    }
    return {};
  },

  getIdentity: async () => {
    try {
      const { data } = await api.get("/api/auth/me");
      return data.user as Identity;
    } catch {
      return null;
    }
  },

  getPermissions: async () => {
    try {
      const { data } = await api.get("/api/auth/me");
      return data.user?.role as string;
    } catch {
      return null;
    }
  },
};
