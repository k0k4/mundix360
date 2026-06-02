"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { PageHeader, StatCard, EmptyState } from "@/components/widgets";
import { Card, CardHeader, CardTitle, CardContent, Table, Th, Td, Select, Spinner } from "@/components/ui";
import { formatBytes, formatNumber } from "@/lib/utils";
import { Activity, ArrowDownUp, Package } from "lucide-react";

function cleanIp(ip: string) {
  return ip?.replace("::ffff:", "") ?? ip;
}

export default function FlowsPage() {
  const [minutes, setMinutes] = useState(60);
  const { data, isLoading } = useApi<any>(`/api/flows/summary?minutes=${minutes}`);
  const totals = data?.totals ?? {};

  return (
    <div>
      <PageHeader
        title="Fluxos (NetFlow)"
        description="Tráfego de rede coletado pelo Akvorado."
        actions={
          <Select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
            <option value={15}>Últimos 15min</option>
            <option value={60}>Última 1h</option>
            <option value={360}>Últimas 6h</option>
            <option value={1440}>Últimas 24h</option>
          </Select>
        }
      />

      {isLoading && !data ? (
        <div className="flex items-center gap-2 text-muted-foreground"><Spinner /> Carregando…</div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Fluxos" value={formatNumber(Number(totals.flows || 0))} icon={<Activity className="h-5 w-5" />} accent="brand" />
            <StatCard label="Volume" value={formatBytes(Number(totals.bytes || 0))} icon={<ArrowDownUp className="h-5 w-5" />} accent="info" />
            <StatCard label="Pacotes" value={formatNumber(Number(totals.packets || 0))} icon={<Package className="h-5 w-5" />} />
          </div>

          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TalkerCard title="Top Origens" rows={data?.top_src} keyName="src" />
            <TalkerCard title="Top Destinos" rows={data?.top_dst} keyName="dst" />
          </div>
          {data?.error && <p className="mt-4 text-sm text-amber-400">{data.error}</p>}
        </>
      )}
    </div>
  );
}

function TalkerCard({ title, rows, keyName }: { title: string; rows: any[]; keyName: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {rows?.length ? (
          <Table>
            <thead>
              <tr>
                <Th>Endereço</Th>
                <Th className="text-right">Volume</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={r[keyName]} className="hover:bg-muted/30">
                  <Td className="font-mono text-xs">{cleanIp(r[keyName])}</Td>
                  <Td className="text-right">{formatBytes(Number(r.bytes))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <EmptyState message="Sem dados" />
        )}
      </CardContent>
    </Card>
  );
}
