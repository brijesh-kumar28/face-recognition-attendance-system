import { create } from "zustand";
import api from "@/lib/axios";
import type { User, AuthState, LoginResponse } from "@/lib/types";

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: typeof window !== "undefined" ? localStorage.getItem("token") : null,
  isAuthenticated: false,
  isLoading: true,

  login: async (email: string, password: string) => {
    const res = await api.post<LoginResponse>("/api/auth/login", {
      email,
      password,
    });
    const { token, user } = res.data;
    localStorage.setItem("token", token);
    set({ user, token, isAuthenticated: true, isLoading: false });
  },

  logout: () => {
    localStorage.removeItem("token");
    set({ user: null, token: null, isAuthenticated: false, isLoading: false });
  },

  fetchUser: async () => {
    try {
      const token = localStorage.getItem("token");
      if (!token) {
        set({ isLoading: false });
        return;
      }
      const res = await api.get<User>("/api/auth/me");
      set({
        user: res.data,
        token,
        isAuthenticated: true,
        isLoading: false,
      });
    } catch {
      localStorage.removeItem("token");
      set({
        user: null,
        token: null,
        isAuthenticated: false,
        isLoading: false,
      });
    }
  },
}));
