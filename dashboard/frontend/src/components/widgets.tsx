"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Card } from "./ui";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  icon?: React.ReactNode;
  accent?: "brand" | "danger" | "warning" | "info";
}) {
  const accents = {
    brand: "text-brand",
    danger: "text-red-400",
    warning: "text-amber-400",
    info: "text-sky-400",
  };
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        {icon && <div className={cn(accent ? accents[accent] : "text-muted-foreground")}>{icon}</div>}
      </div>
      <div className={cn("mt-2 text-2xl font-semibold", accent && accents[accent])}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function HealthDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          ok ? "bg-emerald-400 shadow-[0_0_6px] shadow-emerald-400/60" : "bg-red-400"
        )}
      />
      <span className="text-muted-foreground">{label}</span>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
      {message}
    </div>
  );
}

export function ProgressBar({ pct, danger }: { pct: number; danger?: boolean }) {
  const color = pct >= 90 ? "bg-red-500" : pct >= 75 ? "bg-amber-500" : "bg-brand";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full transition-all", danger ? "bg-red-500" : color)}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  );
}
