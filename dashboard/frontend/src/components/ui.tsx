import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card/60 shadow-sm backdrop-blur-sm",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-5 pb-2", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn("text-sm font-medium text-muted-foreground", className)} {...props} />
  );
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pt-2", className)} {...props} />;
}

type BadgeVariant = "default" | "success" | "warning" | "danger" | "info" | "muted";

const badgeStyles: Record<BadgeVariant, string> = {
  default: "bg-muted text-foreground",
  success: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  danger: "bg-red-500/15 text-red-400 border-red-500/30",
  info: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  muted: "bg-muted/50 text-muted-foreground border-border",
};

export function Badge({
  variant = "default",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-transparent px-2 py-0.5 text-xs font-medium",
        badgeStyles[variant],
        className
      )}
      {...props}
    />
  );
}

export function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "ghost" | "danger";
  size?: "default" | "sm" | "icon";
}) {
  const variants = {
    default: "bg-brand text-black hover:bg-brand-dim font-medium",
    outline: "border border-border bg-transparent hover:bg-muted",
    ghost: "hover:bg-muted",
    danger: "bg-red-500/90 text-white hover:bg-red-500",
  };
  const sizes = {
    default: "h-9 px-4 text-sm",
    sm: "h-8 px-3 text-xs",
    icon: "h-9 w-9",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md transition-colors disabled:opacity-50 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  );
}

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-md border border-input bg-background/60 px-3 text-sm outline-none placeholder:text-muted-foreground focus:border-brand focus:ring-1 focus:ring-brand",
        className
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 rounded-md border border-input bg-background/60 px-2 text-sm outline-none focus:border-brand",
        className
      )}
      {...props}
    />
  );
}

export function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full text-sm", className)} {...props} />
    </div>
  );
}

export function Th({ className, ...props }: React.HTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "border-b border-border px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground",
        className
      )}
      {...props}
    />
  );
}

export function Td({ className, ...props }: React.HTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn("border-b border-border/50 px-3 py-2 align-middle", className)} {...props} />
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "h-4 w-4 animate-spin rounded-full border-2 border-muted border-t-brand",
        className
      )}
    />
  );
}

export function severityVariant(sev: number): BadgeVariant {
  if (sev >= 4) return "danger";
  if (sev >= 3) return "warning";
  if (sev >= 2) return "info";
  return "muted";
}
