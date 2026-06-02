"use client";

import { useApi } from "@/lib/api";
import { PageHeader, StatCard, ProgressBar } from "@/components/widgets";
import { Card, CardHeader, CardTitle, CardContent, Badge, Spinner } from "@/components/ui";
import { formatBytes } from "@/lib/utils";
import { Cpu, MemoryStick, HardDrive } from "lucide-react";

export default function SystemPage() {
  const { data: svc } = useApi<any>("/api/system/services");
  const { data: m } = useApi<any>("/api/system/metrics");

  return (
    <div>
      <PageHeader title="Sistema" description="Serviços da plataforma e recursos do host." />

      {m ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Card className="p-5">
            <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
              <Cpu className="h-4 w-4" /> CPU
            </div>
            <div className="mb-2 text-2xl font-semibold">{m.load_pct}%</div>
            <ProgressBar pct={m.load_pct} />
            <div className="mt-1 text-xs text-muted-foreground">
              load {m.load["1m"]} / {m.load["5m"]} / {m.load["15m"]} · {m.cpu_count} vCPU
            </div>
          </Card>
          <Card className="p-5">
            <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
              <MemoryStick className="h-4 w-4" /> Memória
            </div>
            <div className="mb-2 text-2xl font-semibold">{m.memory.used_pct}%</div>
            <ProgressBar pct={m.memory.used_pct} />
            <div className="mt-1 text-xs text-muted-foreground">
              {formatBytes(m.memory.used_kb * 1024)} / {formatBytes(m.memory.total_kb * 1024)}
            </div>
          </Card>
          <Card className="p-5">
            <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
              <HardDrive className="h-4 w-4" /> Disco /
            </div>
            <div className="mb-2 text-2xl font-semibold">{m.disk.used_pct}%</div>
            <ProgressBar pct={m.disk.used_pct} />
            <div className="mt-1 text-xs text-muted-foreground">
              {formatBytes(m.disk.used_bytes)} / {formatBytes(m.disk.total_bytes)}
            </div>
          </Card>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-muted-foreground"><Spinner /> Carregando…</div>
      )}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Serviços da Plataforma</CardTitle>
        </CardHeader>
        <CardContent>
          {svc?.services ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {svc.services.map((s: any) => (
                <div
                  key={s.name}
                  className="flex items-center justify-between rounded-md border border-border/50 bg-background/40 px-3 py-2"
                >
                  <span className="truncate font-mono text-xs">{s.name}</span>
                  <Badge variant={s.running ? "success" : "danger"}>{s.active}</Badge>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-muted-foreground"><Spinner /> Carregando…</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
