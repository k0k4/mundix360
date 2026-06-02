"use client";

import {
  ShieldAlert,
  Ban,
  Cpu,
  MemoryStick,
  HardDrive,
  AlertTriangle,
} from "lucide-react";
import { useApi } from "@/lib/api";
import { PageHeader, StatCard, HealthDot, ProgressBar, EmptyState } from "@/components/widgets";
import { Card, CardHeader, CardTitle, CardContent, Badge, Spinner } from "@/components/ui";
import { formatBytes, formatNumber } from "@/lib/utils";

export default function OverviewPage() {
  const { data, isLoading } = useApi<any>("/api/overview");

  const host = data?.host;
  const services: any[] = data?.services ?? [];
  const runningCount = services.filter((s) => s.running).length;

  return (
    <div>
      <PageHeader
        title="Visão Geral"
        description="Estado consolidado da plataforma de segurança."
        actions={
          data && (
            <div className="flex flex-wrap items-center gap-4">
              <HealthDot ok={data.health.clickhouse} label="ClickHouse" />
              <HealthDot ok={data.health.victoriametrics} label="Metrics" />
              <HealthDot ok={data.health.loki} label="Loki" />
            </div>
          )
        }
      />

      {isLoading && !data ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Carregando…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Alertas (24h)"
              value={formatNumber(data.siem.alerts_24h)}
              hint={`${formatNumber(data.siem.alerts_high_24h)} de alta severidade`}
              icon={<ShieldAlert className="h-5 w-5" />}
              accent="info"
            />
            <StatCard
              label="Alta Severidade (24h)"
              value={formatNumber(data.siem.alerts_high_24h)}
              hint="severidade ≥ 3"
              icon={<AlertTriangle className="h-5 w-5" />}
              accent="warning"
            />
            <StatCard
              label="IPs Bloqueados"
              value={formatNumber(data.firewall.blocked_ips)}
              hint="firewall ativo"
              icon={<Ban className="h-5 w-5" />}
              accent="danger"
            />
            <StatCard
              label="Serviços Ativos"
              value={`${runningCount}/${services.length}`}
              hint="plataforma"
              accent="brand"
            />
          </div>

          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Recursos do Host</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <ResourceRow
                  icon={<Cpu className="h-4 w-4" />}
                  label="CPU"
                  value={`${host.load_pct}%`}
                  sub={`load ${host.load["1m"]} · ${host.cpu_count} vCPU`}
                  pct={host.load_pct}
                />
                <ResourceRow
                  icon={<MemoryStick className="h-4 w-4" />}
                  label="Memória"
                  value={`${host.memory.used_pct}%`}
                  sub={`${formatBytes(host.memory.used_kb * 1024)} / ${formatBytes(
                    host.memory.total_kb * 1024
                  )}`}
                  pct={host.memory.used_pct}
                />
                <ResourceRow
                  icon={<HardDrive className="h-4 w-4" />}
                  label="Disco /"
                  value={`${host.disk.used_pct}%`}
                  sub={`${formatBytes(host.disk.used_bytes)} / ${formatBytes(
                    host.disk.total_bytes
                  )}`}
                  pct={host.disk.used_pct}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Top Fontes de Alertas (24h)</CardTitle>
              </CardHeader>
              <CardContent>
                {data.siem.top_sources?.length ? (
                  <div className="space-y-2">
                    {data.siem.top_sources.map((s: any) => (
                      <div key={s.source} className="flex items-center justify-between text-sm">
                        <span className="font-mono">{s.source}</span>
                        <Badge variant="info">{formatNumber(s.count)}</Badge>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState message="Sem alertas recentes" />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Serviços</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto pr-1">
                  {services.map((s) => (
                    <div key={s.name} className="flex items-center justify-between text-sm">
                      <span className="truncate font-mono text-xs">{s.name}</span>
                      <Badge variant={s.running ? "success" : "danger"}>
                        {s.active}
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function ResourceRow({
  icon,
  label,
  value,
  sub,
  pct,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
  pct: number;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 text-muted-foreground">
          {icon}
          {label}
        </span>
        <span className="font-medium">{value}</span>
      </div>
      <ProgressBar pct={pct} />
      <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
    </div>
  );
}
