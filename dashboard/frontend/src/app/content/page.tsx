"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { useApi, apiPost, apiDelete } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/widgets";
import {
  Card,
  CardContent,
  Badge,
  Table,
  Th,
  Td,
  Input,
  Button,
  Spinner,
} from "@/components/ui";
import { Ban, Plus, Trash2 } from "lucide-react";

export default function ContentPage() {
  const { mutate } = useSWRConfig();
  const { data, isLoading } = useApi<any>("/api/content/blocklist");
  const [domain, setDomain] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function add() {
    setError("");
    setBusy(true);
    try {
      await apiPost("/api/content/blocklist", { domain, note });
      setDomain("");
      setNote("");
      mutate("/api/content/blocklist");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(d: string) {
    setBusy(true);
    try {
      await apiDelete(`/api/content/blocklist/${d}`);
      mutate("/api/content/blocklist");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Filtro de Conteúdo"
        description="Bloqueio de domínios via DNS sinkhole (dnsmasq)."
      />

      <Card className="mb-5">
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[200px]">
              <label className="mb-1 block text-xs text-muted-foreground">Domínio</label>
              <Input
                placeholder="ex: malware.example.com"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              />
            </div>
            <div className="flex-1 min-w-[160px]">
              <label className="mb-1 block text-xs text-muted-foreground">Nota (opcional)</label>
              <Input value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <Button onClick={add} disabled={!domain || busy}>
              {busy ? <Spinner /> : <Ban className="h-4 w-4" />} Bloquear domínio
            </Button>
          </div>
          {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
          <p className="mt-3 text-xs text-muted-foreground">
            Domínios bloqueados resolvem para <span className="font-mono">0.0.0.0</span>. O dnsmasq é
            recarregado automaticamente.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-medium">Domínios Bloqueados</h3>
            <Badge variant="danger">{data?.count ?? 0}</Badge>
          </div>
          {isLoading && !data ? (
            <div className="flex items-center gap-2 py-6 text-muted-foreground"><Spinner /> Carregando…</div>
          ) : data?.domains?.length ? (
            <Table>
              <thead>
                <tr>
                  <Th>Domínio</Th>
                  <Th>Nota</Th>
                  <Th className="w-24 text-right">Ação</Th>
                </tr>
              </thead>
              <tbody>
                {data.domains.map((d: any) => (
                  <tr key={d.domain} className="hover:bg-muted/30">
                    <Td className="font-mono">{d.domain}</Td>
                    <Td className="text-xs text-muted-foreground">{d.note || "—"}</Td>
                    <Td className="text-right">
                      <Button size="sm" variant="outline" onClick={() => remove(d.domain)} disabled={busy}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState message="Nenhum domínio bloqueado." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
