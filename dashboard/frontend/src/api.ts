import axios from "axios";

export const api = axios.create({
  baseURL: "",
  headers: { "Content-Type": "application/json" },
  // Session auth uses an HttpOnly cookie; it must travel with every request.
  withCredentials: true,
});

// Optional static token (machine/back-compat). Cookie sessions are preferred.
const token = import.meta.env.VITE_API_TOKEN;
if (token) {
  api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
}

// Any 401 means the session is gone/expired: drop the user at the login screen.
// We ignore 401s from the auth probes themselves (login/setup/state/me), which
// the auth flow handles explicitly, to avoid redirect loops.
api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status;
    const url: string = error?.config?.url || "";
    const isAuthProbe = url.includes("/api/auth/");
    if (status === 401 && !isAuthProbe) {
      const setup = error?.response?.headers?.["x-mundix-setup"] === "required";
      const target = setup ? "/setup" : "/login";
      if (window.location.pathname !== target) {
        window.location.assign(target);
      }
    }
    return Promise.reject(error);
  }
);
