"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/widgets";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  Table,
  Th,
  Td,
  Input,
  Select,
  Spinner,
  severityVariant,
} from "@/components/ui";
import { fmtDateTime, formatNumber, timeAgo } from "@/lib/utils";
import {
  BarChart,
  Bar,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

export default function SiemPage() {
  const [hours, setHours] = useState(24);
  const [search, setSearch] = useState("");
  const [minSev, setMinSev] = useState(0);
  const [source, setSource] = useState("");

  const params = new URLSearchParams({
    hours: String(hours),
    min_severity: String(minSev),
    limit: "100",
  });
  if (search) params.set("search", search);
  if (source) params.set("source", source);

  const { data, isLoading } = useApi<any>(`/api/alerts?${params.toString()}`);
  const { data: stats } = useApi<any>(`/api/alerts/stats?hours=${hours}`);

  const timeline = (stats?.timeline ?? []).map((t: any) => ({
    hour: new Date(t.hour + "Z").toLocaleTimeString("pt-BR", { hour: "2-digit" }),
    count: Number(t.count),
  }));

  return (
    <div>
      <PageHeader
        title="SIEM / Alertas"
        description="Eventos de segurança correlacionados (ClickHouse)."
        actions={
          <Select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            <option value={1}>Última 1h</option>
            <option value={6}>Últimas 6h</option>
            <option value={24}>Últimas 24h</option>
            <option value={168}>Últimos 7d</option>
          </Select>
        }
      />

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Linha do Tempo de Alertas</CardTitle>
          </CardHeader>
          <CardContent>
            {timeline.length ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={timeline}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" vertical={false} />
                  <XAxis dataKey="hour" stroke="#64748b" fontSize={11} tickLine={false} />
                  <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{
                      background: "#0f1117",
                      border: "1px solid #1e293b",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="count" fill="#10b981" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="Sem dados" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Por Severidade</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {(stats?.by_severity ?? []).map((s: any) => (
                <div key={s.severity} className="flex items-center justify-between text-sm">
                  <Badge variant={severityVariant(Number(s.severity))}>
                    sev {s.severity}
                  </Badge>
                  <span className="font-medium">{formatNumber(Number(s.count))}</span>
                </div>
              ))}
              {!stats?.by_severity?.length && <EmptyState message="Sem dados" />}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-5">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Input
              placeholder="Buscar regra, descrição ou IP…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-xs"
            />
            <Select value={minSev} onChange={(e) => setMinSev(Number(e.target.value))}>
              <option value={0}>Toda severidade</option>
              <option value={2}>≥ 2</option>
              <option value={3}>≥ 3 (alta)</option>
              <option value={4}>≥ 4 (crítica)</option>
            </Select>
            <Select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Toda fonte</option>
              {(stats?.by_source ?? []).map((s: any) => (
                <option key={s.source} value={s.source}>
                  {s.source}
                </option>
              ))}
            </Select>
            <div className="ml-auto text-sm text-muted-foreground">
              {data ? `${formatNumber(data.total)} eventos` : ""}
            </div>
          </div>

          {isLoading && !data ? (
            <div className="flex items-center gap-2 py-8 text-muted-foreground">
              <Spinner /> Carregando…
            </div>
          ) : data?.alerts?.length ? (
            <Table>
              <thead>
                <tr>
                  <Th>Quando</Th>
                  <Th>Sev</Th>
                  <Th>Fonte</Th>
                  <Th>Regra</Th>
                  <Th>Origem → Destino</Th>
                  <Th>Categoria</Th>
                </tr>
              </thead>
              <tbody>
                {data.alerts.map((a: any) => (
                  <tr key={a.event_id} className="hover:bg-muted/30">
                    <Td className="whitespace-nowrap text-xs text-muted-foreground" title={fmtDateTime(a.timestamp)}>
                      {timeAgo(a.timestamp)}
                    </Td>
                    <Td>
                      <Badge variant={severityVariant(a.severity)}>{a.severity}</Badge>
                    </Td>
                    <Td className="font-mono text-xs">{a.source}</Td>
                    <Td className="max-w-xs truncate" title={a.rule_name}>
                      {a.rule_name}
                      {a.false_positive ? (
                        <Badge variant="muted" className="ml-2">FP</Badge>
                      ) : null}
                    </Td>
                    <Td className="font-mono text-xs">
                      {a.src_ip || "—"}
                      {a.dst_ip ? ` → ${a.dst_ip}` : ""}
                    </Td>
                    <Td className="text-xs text-muted-foreground">{a.category || "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState message="Nenhum alerta encontrado para os filtros." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
