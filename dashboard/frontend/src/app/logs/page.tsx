"use client";

import { useState } from "react";
import { useApi } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/widgets";
import { Card, CardContent, Badge, Select, Input, Button, Spinner } from "@/components/ui";
import { Search } from "lucide-react";

const PRESETS = [
  { label: "Suricata (IDS)", q: '{job="suricata"}' },
  { label: "DNS (dnsmasq)", q: '{job="dnsmasq"}' },
  { label: "Todos", q: '{job=~".+"}' },
];

export default function LogsPage() {
  const [query, setQuery] = useState(PRESETS[0].q);
  const [input, setInput] = useState(PRESETS[0].q);
  const [hours, setHours] = useState(1);

  const params = new URLSearchParams({ query, limit: "200", hours: String(hours) });
  const { data, isLoading } = useApi<any>(`/api/logs?${params.toString()}`, {
    refreshInterval: 10000,
  });

  return (
    <div>
      <PageHeader title="Logs" description="Consulta de logs agregados (Loki)." />

      <Card className="mb-5">
        <CardContent className="pt-5">
          <div className="mb-3 flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <Button
                key={p.label}
                size="sm"
                variant={query === p.q ? "default" : "outline"}
                onClick={() => {
                  setQuery(p.q);
                  setInput(p.q);
                }}
              >
                {p.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setQuery(input)}
              className="flex-1 font-mono text-xs"
              placeholder='{job="suricata"}'
            />
            <Select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              <option value={1}>1h</option>
              <option value={6}>6h</option>
              <option value={24}>24h</option>
            </Select>
            <Button onClick={() => setQuery(input)}>
              <Search className="h-4 w-4" /> Buscar
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-medium">Resultados</h3>
            <Badge variant="info">{data?.count ?? 0}</Badge>
          </div>
          {isLoading && !data ? (
            <div className="flex items-center gap-2 py-6 text-muted-foreground"><Spinner /> Carregando…</div>
          ) : data?.entries?.length ? (
            <div className="max-h-[60vh] space-y-1 overflow-y-auto font-mono text-xs">
              {data.entries.map((e: any, i: number) => (
                <div key={i} className="flex gap-3 rounded border-l-2 border-brand/30 bg-background/40 px-3 py-1.5">
                  <span className="shrink-0 text-muted-foreground">
                    {new Date(e.timestamp / 1e6).toLocaleTimeString("pt-BR", { hour12: false })}
                  </span>
                  {e.labels?.job && (
                    <span className="shrink-0 text-brand">[{e.labels.job}]</span>
                  )}
                  <span className="break-all text-foreground/90">{e.line}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState message={data?.error || "Nenhum log encontrado."} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
