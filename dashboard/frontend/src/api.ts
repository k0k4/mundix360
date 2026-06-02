import axios from "axios";

export const api = axios.create({
  baseURL: "",
  headers: { "Content-Type": "application/json" },
});

const token = import.meta.env.VITE_API_TOKEN;
if (token) {
  api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
}
