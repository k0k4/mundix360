import { useCallback, useEffect, useState } from "react";
import {
  Table,
  Tag,
  Empty,
  Button,
  Space,
  Progress,
  Row,
  Col,
  Card,
  Tooltip,
  Badge,
  message as antdMessage,
} from "antd";
import {
  NodeIndexOutlined,
  ReloadOutlined,
  PushpinOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { fmtTime } from "../../format";
import { PageHeader } from "../../components/ui";

type Lease = {
  ip: string;
  mac: string;
  hostname: string | null;
  zone: string | null;
  expiry: number;
  presence: "seen" | "down" | "unknown";
  neighbor_state: string | null;
  is_reserved: boolean;
};

type Pool = {
  zone: string;
  interface: string | null;
  supported: boolean;
  pool_size: number | null;
  active: number | null;
  utilization: number | null;
};

const PRESENCE: Record<string, { color: string; label: string }> = {
  seen: { color: "#22c55e", label: "Online" },
  down: { color: "#ef4444", label: "Offline" },
  unknown: { color: "#64748b", label: "Desconhecido" },
};

export const LeasesPage = () => {
  const [leases, setLeases] = useState<Lease[]>([]);
  const [pools, setPools] = useState<Pool[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, p] = await Promise.all([
        api.get("/api/network/dhcp-leases"),
        api.get("/api/network/dhcp/pools"),
      ]);
      setLeases(l.data.leases || []);
      setPools(p.data.pools || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const reserve = async (mac: string) => {
    try {
      await api.post(
        `/api/network/dhcp-leases/${encodeURIComponent(mac)}/reserve`,
      );
      antdMessage.success("Lease convertido em reserva estática.");
      load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao reservar");
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <NodeIndexOutlined /> Rede · DHCP
          </>
        }
        title="Leases & Pools"
        subtitle="Concessões DHCP ativas, presença na rede (tabela de vizinhança) e utilização dos pools."
        extra={
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            Atualizar
          </Button>
        }
      />

      <Row gutter={16} style={{ marginBottom: 20 }}>
        {pools.map((p) => (
          <Col xs={24} sm={12} lg={8} key={p.zone}>
            <Card size="small" style={{ marginBottom: 12 }}>
              <Space
                style={{ width: "100%", justifyContent: "space-between" }}
              >
                <Space>
                  <Tag color="blue">{p.zone}</Tag>
                  <span className="mx-mono" style={{ fontSize: 12 }}>
                    {p.interface}
                  </span>
                </Space>
                {p.supported ? (
                  <span style={{ fontSize: 12, color: "#93a4c0" }}>
                    {p.active}/{p.pool_size}
                  </span>
                ) : (
                  <Tag>sem pool</Tag>
                )}
              </Space>
              {p.supported && (
                <Progress
                  percent={p.utilization ?? 0}
                  size="small"
                  status={(p.utilization ?? 0) > 85 ? "exception" : "active"}
                  style={{ marginTop: 8 }}
                />
              )}
            </Card>
          </Col>
        ))}
      </Row>

      <Table
        dataSource={leases}
        loading={loading}
        rowKey={(r: Lease) => r.mac || r.ip}
        size="middle"
        locale={{ emptyText: <Empty description="Nenhum lease ativo" /> }}
      >
        <Table.Column
          title="Status"
          dataIndex="presence"
          width={130}
          render={(p: string, r: Lease) => {
            const info = PRESENCE[p] || PRESENCE.unknown;
            return (
              <Tooltip
                title={
                  r.neighbor_state
                    ? `Estado vizinhança: ${r.neighbor_state}`
                    : "Sem entrada na tabela de vizinhança"
                }
              >
                <Badge color={info.color} text={info.label} />
              </Tooltip>
            );
          }}
        />
        <Table.Column
          title="IP"
          dataIndex="ip"
          render={(i) => <span className="mx-mono">{i}</span>}
        />
        <Table.Column
          title="MAC"
          dataIndex="mac"
          render={(m) => <span className="mx-mono">{m}</span>}
        />
        <Table.Column
          title="Hostname"
          dataIndex="hostname"
          render={(h) => h || <Tag>—</Tag>}
        />
        <Table.Column
          title="Zona"
          dataIndex="zone"
          render={(z) => (z ? <Tag color="blue">{z}</Tag> : "—")}
        />
        <Table.Column
          title="Expira"
          dataIndex="expiry"
          render={(e) => (e ? fmtTime(e * 1000) : "—")}
        />
        <Table.Column
          title="Ações"
          width={150}
          render={(_, r: Lease) =>
            r.is_reserved ? (
              <Tag color="green" icon={<PushpinOutlined />}>
                reservado
              </Tag>
            ) : (
              <Button
                size="small"
                icon={<PushpinOutlined />}
                onClick={() => reserve(r.mac)}
              >
                Reservar
              </Button>
            )
          }
        />
      </Table>
    </div>
  );
};
