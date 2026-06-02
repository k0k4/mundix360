"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { useApi, apiPost, apiDelete } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/widgets";
import { Tabs } from "@/components/tabs";
import {
  Card,
  CardContent,
  Badge,
  Table,
  Th,
  Td,
  Input,
  Select,
  Button,
  Spinner,
} from "@/components/ui";
import { Ban, Plus, Trash2, ShieldX } from "lucide-react";

export default function FirewallPage() {
  const [tab, setTab] = useState("blocklist");
  return (
    <div>
      <PageHeader
        title="Firewall"
        description="Gestão completa: regras nftables, bloqueio de IPs e portas."
      />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "blocklist", label: "Blocklist de IP" },
          { id: "ports", label: "Regras de Porta" },
          { id: "ruleset", label: "Ruleset (nftables)" },
        ]}
      />
      {tab === "blocklist" && <BlocklistTab />}
      {tab === "ports" && <PortRulesTab />}
      {tab === "ruleset" && <RulesetTab />}
    </div>
  );
}

function BlocklistTab() {
  const { mutate } = useSWRConfig();
  const { data, isLoading } = useApi<any>("/api/firewall/blocklist");
  const [ip, setIp] = useState("");
  const [duration, setDuration] = useState(3600);
  const [reason, setReason] = useState("dashboard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function block() {
    setError("");
    setBusy(true);
    try {
      await apiPost("/api/firewall/blocklist", { ip, duration, reason });
      setIp("");
      mutate("/api/firewall/blocklist");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function unblock(target: string) {
    setBusy(true);
    try {
      await apiDelete(`/api/firewall/blocklist/${target}`);
      mutate("/api/firewall/blocklist");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[180px]">
              <label className="mb-1 block text-xs text-muted-foreground">Endereço IP</label>
              <Input placeholder="ex: 203.0.113.10" value={ip} onChange={(e) => setIp(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Duração</label>
              <Select value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
                <option value={3600}>1 hora</option>
                <option value={21600}>6 horas</option>
                <option value={86400}>24 horas</option>
                <option value={604800}>7 dias</option>
                <option value={2592000}>30 dias</option>
              </Select>
            </div>
            <div className="flex-1 min-w-[140px]">
              <label className="mb-1 block text-xs text-muted-foreground">Motivo</label>
              <Input value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <Button onClick={block} disabled={!ip || busy}>
              {busy ? <Spinner /> : <Ban className="h-4 w-4" />} Bloquear
            </Button>
          </div>
          {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-medium">IPs Bloqueados</h3>
            <Badge variant="danger">{data?.count ?? 0}</Badge>
          </div>
          {isLoading && !data ? (
            <div className="flex items-center gap-2 py-6 text-muted-foreground"><Spinner /> Carregando…</div>
          ) : data?.blocked?.length ? (
            <Table>
              <thead>
                <tr>
                  <Th>IP</Th>
                  <Th className="w-24 text-right">Ação</Th>
                </tr>
              </thead>
              <tbody>
                {data.blocked.map((b: any) => (
                  <tr key={b.ip} className="hover:bg-muted/30">
                    <Td className="font-mono">{b.ip}</Td>
                    <Td className="text-right">
                      <Button size="sm" variant="danger" onClick={() => unblock(b.ip)} disabled={busy}>
                        <Trash2 className="h-3.5 w-3.5" /> Remover
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState message="Nenhum IP bloqueado no momento." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function PortRulesTab() {
  const { mutate } = useSWRConfig();
  const { data, isLoading } = useApi<any>("/api/firewall/input-rules");
  const [proto, setProto] = useState("tcp");
  const [port, setPort] = useState("");
  const [action, setAction] = useState("accept");
  const [iif, setIif] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function add() {
    setError("");
    setBusy(true);
    try {
      await apiPost("/api/firewall/port-rules", {
        proto,
        port: Number(port),
        action,
        iif: iif || null,
      });
      setPort("");
      mutate("/api/firewall/input-rules");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function del(handle: number) {
    setBusy(true);
    try {
      await apiDelete(`/api/firewall/input-rules/${handle}`);
      mutate("/api/firewall/input-rules");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Protocolo</label>
              <Select value={proto} onChange={(e) => setProto(e.target.value)}>
                <option value="tcp">TCP</option>
                <option value="udp">UDP</option>
              </Select>
            </div>
            <div className="w-28">
              <label className="mb-1 block text-xs text-muted-foreground">Porta</label>
              <Input placeholder="443" value={port} onChange={(e) => setPort(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Ação</label>
              <Select value={action} onChange={(e) => setAction(e.target.value)}>
                <option value="accept">Permitir</option>
                <option value="drop">Bloquear</option>
              </Select>
            </div>
            <div className="w-36">
              <label className="mb-1 block text-xs text-muted-foreground">Interface (opc.)</label>
              <Input placeholder="ens19" value={iif} onChange={(e) => setIif(e.target.value)} />
            </div>
            <Button onClick={add} disabled={!port || busy}>
              {busy ? <Spinner /> : <Plus className="h-4 w-4" />} Adicionar regra
            </Button>
          </div>
          {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
          <p className="mt-3 text-xs text-muted-foreground">
            Regras são aplicadas à chain <span className="font-mono">inet filter input</span>.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <h3 className="mb-3 text-sm font-medium">Regras da Chain INPUT</h3>
          {isLoading && !data ? (
            <div className="flex items-center gap-2 py-6 text-muted-foreground"><Spinner /> Carregando…</div>
          ) : data?.rules?.length ? (
            <Table>
              <thead>
                <tr>
                  <Th className="w-16">Handle</Th>
                  <Th>Regra</Th>
                  <Th className="w-24 text-right">Ação</Th>
                </tr>
              </thead>
              <tbody>
                {data.rules.map((r: any) => (
                  <tr key={r.handle} className="hover:bg-muted/30">
                    <Td className="font-mono text-xs text-muted-foreground">{r.handle}</Td>
                    <Td className="font-mono text-xs">{r.expr}</Td>
                    <Td className="text-right">
                      <Button size="sm" variant="outline" onClick={() => del(r.handle)} disabled={busy}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState message="Sem regras." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RulesetTab() {
  const { data, isLoading } = useApi<any>("/api/firewall/ruleset");
  if (isLoading && !data)
    return <div className="flex items-center gap-2 text-muted-foreground"><Spinner /> Carregando…</div>;
  return (
    <div className="space-y-5">
      {data?.tables?.map((t: any) => (
        <Card key={`${t.family}/${t.name}`}>
          <CardContent className="pt-5">
            <div className="mb-3 flex items-center gap-2">
              <ShieldX className="h-4 w-4 text-brand" />
              <span className="font-mono text-sm">
                table {t.family} {t.name}
              </span>
            </div>
            <div className="space-y-4">
              {t.chains.map((c: any) => (
                <div key={c.name}>
                  <div className="mb-1 flex items-center gap-2 text-xs">
                    <span className="font-mono font-medium">chain {c.name}</span>
                    {c.hook && <Badge variant="info">{c.hook}</Badge>}
                    {c.policy && (
                      <Badge variant={c.policy === "drop" ? "danger" : "success"}>
                        policy {c.policy}
                      </Badge>
                    )}
                  </div>
                  <div className="space-y-0.5 rounded-md bg-background/40 p-2 font-mono text-xs text-muted-foreground">
                    {c.rules.length ? (
                      c.rules.map((r: any) => (
                        <div key={r.handle} className="flex gap-2">
                          <span className="text-muted-foreground/50">#{r.handle}</span>
                          <span className="text-foreground/90">{r.expr}</span>
                        </div>
                      ))
                    ) : (
                      <span className="opacity-50">(vazio)</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
