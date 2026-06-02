"use client";

import useSWR, { SWRConfiguration } from "swr";

export async function fetcher<T = any>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" } });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export function useApi<T = any>(path: string | null, config?: SWRConfiguration) {
  return useSWR<T>(path, fetcher, {
    refreshInterval: 15000,
    revalidateOnFocus: false,
    ...config,
  });
}

export async function apiPost<T = any>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function apiDelete<T = any>(path: string): Promise<T> {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}
