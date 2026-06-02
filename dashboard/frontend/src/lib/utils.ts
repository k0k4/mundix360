import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("pt-BR").format(n ?? 0);
}

export function timeAgo(iso: string | number): string {
  const d = typeof iso === "number" ? new Date(iso / 1e6) : new Date(iso + "Z");
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (Number.isNaN(secs)) return "-";
  if (secs < 60) return `${secs}s atrás`;
  if (secs < 3600) return `${Math.floor(secs / 60)}min atrás`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h atrás`;
  return `${Math.floor(secs / 86400)}d atrás`;
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { hour12: false });
}
