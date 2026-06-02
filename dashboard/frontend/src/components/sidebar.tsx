"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  ShieldAlert,
  Flame,
  Network,
  Ban,
  Activity,
  ScrollText,
  Server,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/", label: "Visão Geral", icon: LayoutDashboard },
  { href: "/siem", label: "SIEM / Alertas", icon: ShieldAlert },
  { href: "/firewall", label: "Firewall", icon: Flame },
  { href: "/network", label: "Rede / VLANs", icon: Network },
  { href: "/content", label: "Filtro de Conteúdo", icon: Ban },
  { href: "/flows", label: "Fluxos (NetFlow)", icon: Activity },
  { href: "/logs", label: "Logs", icon: ScrollText },
  { href: "/system", label: "Sistema", icon: Server },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-col border-r border-border bg-card/40 backdrop-blur-md">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand/15 ring-1 ring-brand/30">
          <ShieldCheck className="h-5 w-5 text-brand" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Mundix</div>
          <div className="text-xs text-muted-foreground">Security 360</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-2">
        {nav.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-brand/15 text-brand ring-1 ring-brand/20"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-5 py-4 text-[11px] text-muted-foreground">
        <div>v1.0.0 · 100% Open Source</div>
      </div>
    </aside>
  );
}
