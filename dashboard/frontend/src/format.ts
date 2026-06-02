export function sevColor(sev: number): string {
  if (sev >= 9) return "magenta";
  if (sev >= 7) return "red";
  if (sev >= 5) return "orange";
  if (sev >= 3) return "gold";
  return "blue";
}

export function sevLabel(sev: number): string {
  if (sev >= 9) return `Crítico (${sev})`;
  if (sev >= 7) return `Alto (${sev})`;
  if (sev >= 5) return `Médio (${sev})`;
  if (sev >= 3) return `Baixo (${sev})`;
  return `Info (${sev})`;
}

export function fmtBytes(n: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(n) / Math.log(1024));
  return `${(n / Math.pow(1024, i)).toFixed(1)} ${u[i]}`;
}

export function stripV6(ip?: string): string {
  return (ip ?? "").replace("::ffff:", "");
}

export function fmtTime(v: string | number): string {
  if (typeof v === "number") {
    // loki nanosecond timestamps
    const ms = v > 1e15 ? v / 1e6 : v;
    return new Date(ms).toLocaleString("pt-BR");
  }
  return new Date(v).toLocaleString("pt-BR");
}
