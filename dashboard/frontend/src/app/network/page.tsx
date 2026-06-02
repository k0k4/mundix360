"use client";

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
  Spinner,
} from "@/components/ui";
import { Network as NetIcon } from "lucide-react";

export default function NetworkPage() {
  const { data: zones } = useApi<any>("/api/network/zones");
  const { data: leases } = useApi<any>("/api/network/dhcp-leases");

  return (
    <div>
      <PageHeader
        title="Rede / VLANs"
        description="Zonas, segmentação e concessões DHCP."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {zones?.zones?.map((z: any) => (
          <Card key={z.zone}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <NetIcon className="h-4 w-4 text-brand" />
                Zona {z.zone.toUpperCase()}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Interface" value={<span className="font-mono">{z.interface}</span>} />
              <Row label="Rede" value={<span className="font-mono">{z.network}</span>} />
              <Row label="Gateway DNS" value={<span className="font-mono">{z.listen_address || "—"}</span>} />
              <Row label="Domínio" value={z.domain || "—"} />
              <Row
                label="Faixa DHCP"
                value={
                  z.dhcp_start ? (
                    <span className="font-mono text-xs">
                      {z.dhcp_start} – {z.dhcp_end}
                    </span>
                  ) : (
                    <Badge variant="muted">reservas apenas</Badge>
                  )
                }
              />
              <Row label="Lease" value={z.lease_time || "—"} />
              <div className="pt-1">
                <Badge variant={z.config_present ? "success" : "warning"}>
                  {z.config_present ? "config ativa" : "sem config"}
                </Badge>
              </div>
            </CardContent>
          </Card>
        )) ?? (
          <div className="flex items-center gap-2 text-muted-foreground"><Spinner /> Carregando…</div>
        )}
      </div>

      <Card className="mt-6">
        <CardContent className="pt-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-medium">Concessões DHCP Ativas</h3>
            <Badge variant="info">{leases?.count ?? 0}</Badge>
          </div>
          {leases?.leases?.length ? (
            <Table>
              <thead>
                <tr>
                  <Th>IP</Th>
                  <Th>MAC</Th>
                  <Th>Hostname</Th>
                  <Th>Zona</Th>
                </tr>
              </thead>
              <tbody>
                {leases.leases.map((l: any) => (
                  <tr key={l.mac + l.ip} className="hover:bg-muted/30">
                    <Td className="font-mono">{l.ip}</Td>
                    <Td className="font-mono text-xs">{l.mac}</Td>
                    <Td>{l.hostname || "—"}</Td>
                    <Td>{l.zone ? <Badge variant="info">{l.zone}</Badge> : "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <EmptyState message="Nenhuma concessão DHCP ativa registrada." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  );
}
