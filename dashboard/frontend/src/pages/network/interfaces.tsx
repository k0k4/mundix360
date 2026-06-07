import { useCallback, useEffect, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Select, Button, Space, Typography, Alert,
  Tooltip, message as antdMessage,
} from "antd";
import {
  ApiOutlined, GlobalOutlined, PartitionOutlined, ReloadOutlined,
  DisconnectOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text } = Typography;

type Iface = {
  interface: string;
  address?: string | null;
  addresses?: string[];
  state?: string;
  mac?: string;
  is_wan?: boolean;
  role?: "wan" | "zone" | "unassigned";
  zone?: string | null;
};

type Assignments = {
  wan_iface: string;
  wan_pinned: boolean;
  interfaces: Iface[];
  zones: { name: string; iface: string; net: string }[];
};

const roleTag = (i: Iface) => {
  if (i.role === "wan") return <Tag color="volcano" icon={<GlobalOutlined />}>WAN</Tag>;
  if (i.role === "zone") return <Tag color="blue" icon={<PartitionOutlined />}>{i.zone?.toUpperCase()}</Tag>;
  return <Tag>Livre</Tag>;
};

const stateTag = (s?: string) =>
  s === "up"
    ? <Tag color="green" icon={<ThunderboltOutlined />}>up</Tag>
    : <Tag color="default" icon={<DisconnectOutlined />}>{s || "?"}</Tag>;

export const InterfacesPage = () => {
  const [data, setData] = useState<Assignments | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<Assignments>("/api/network/assignments");
      setData(data);
    } catch {
      msg.error("Falha ao carregar interfaces");
    } finally {
      setLoading(false);
    }
  }, [msg]);

  useEffect(() => { load(); }, [load]);

  const setWan = async (iface: string) => {
    setSaving(true);
    try {
      await api.put("/api/network/wan", { interface: iface });
      msg.success(iface ? `WAN definida para ${iface}` : "WAN em detecção automática");
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao definir WAN");
    } finally {
      setSaving(false);
    }
  };

  const ifaces = data?.interfaces || [];
  const upCount = ifaces.filter((i) => i.state === "up").length;
  const zoneCount = data?.zones?.length || 0;
  const freeCount = ifaces.filter((i) => i.role === "unassigned").length;
  const wanOptions = ifaces.map((i) => ({
    value: i.interface,
    label: `${i.interface}${i.address ? ` · ${i.address}` : ""}${i.state !== "up" ? ` · ${i.state}` : ""}`,
  }));

  return (
    <div>
      {ctx}
      <PageHeader
        eyebrow={<><ApiOutlined /> Hardware de rede</>}
        title="Interfaces"
        subtitle="Detecção automática das placas de rede deste appliance e atribuição de papéis (WAN / zonas). Adapta-se a qualquer hardware."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} md={6}><KpiCard icon={<ApiOutlined />} color="#1677ff" label="Interfaces" value={ifaces.length} /></Col>
        <Col xs={12} md={6}><KpiCard icon={<ThunderboltOutlined />} color="#52c41a" label="Ativas (up)" value={upCount} /></Col>
        <Col xs={12} md={6}><KpiCard icon={<PartitionOutlined />} color="#722ed1" label="Em zonas" value={zoneCount} /></Col>
        <Col xs={12} md={6}><KpiCard icon={<GlobalOutlined />} color="#fa541c" label="Livres" value={freeCount} /></Col>
      </Row>

      <Card bordered={false} className="mx-card" style={{ marginBottom: 16 }}
        title={<><GlobalOutlined /> Interface WAN (uplink / Internet)</>}>
        <Row gutter={16} align="middle">
          <Col xs={24} md={14}>
            <Text type="secondary">
              A WAN é a interface conectada à Internet. Por padrão é detectada pela rota
              default. Você pode fixá-la manualmente — todas as regras de NAT e de zona
              passam a segui-la automaticamente.
            </Text>
          </Col>
          <Col xs={24} md={10}>
            <Space wrap>
              <Select
                style={{ minWidth: 240 }}
                value={data?.wan_pinned ? data?.wan_iface : undefined}
                placeholder={data ? `Auto: ${data.wan_iface || "—"}` : "…"}
                options={wanOptions}
                onChange={setWan}
                loading={saving}
                showSearch
                optionFilterProp="label"
              />
              <Tooltip title="Voltar para detecção automática (rota default)">
                <Button onClick={() => setWan("")} disabled={!data?.wan_pinned || saving}>
                  Auto
                </Button>
              </Tooltip>
            </Space>
            <div style={{ marginTop: 8 }}>
              {data && (
                <Tag color={data.wan_pinned ? "volcano" : "green"}>
                  {data.wan_pinned ? `Fixada: ${data.wan_iface}` : `Automática: ${data.wan_iface || "indefinida"}`}
                </Tag>
              )}
            </div>
          </Col>
        </Row>
      </Card>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="Como atribuir interfaces às zonas"
        description="Cada interface interna vira uma zona ao ser configurada em Rede › VLANs / Zonas (com DHCP/DNS). A WAN é definida acima. Interfaces livres ainda não têm papel." />

      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>Atualizar</Button>
      </Space>

      <Table dataSource={ifaces} rowKey="interface" loading={loading} size="middle"
        pagination={false}>
        <Table.Column title="Interface" dataIndex="interface" width={150}
          render={(v) => <Space><ApiOutlined style={{ color: "#1677ff" }} />
            <span className="mx-mono">{v}</span></Space>} />
        <Table.Column title="Papel" width={130} render={(_, r: Iface) => roleTag(r)} />
        <Table.Column title="Estado" dataIndex="state" width={110} render={stateTag} />
        <Table.Column title="Endereço(s)" render={(_, r: Iface) =>
          r.addresses && r.addresses.length
            ? <Space direction="vertical" size={0}>
                {r.addresses.map((a) => <span key={a} className="mx-mono">{a}</span>)}
              </Space>
            : <Text type="secondary">sem IP</Text>} />
        <Table.Column title="MAC" dataIndex="mac" width={160}
          render={(v) => <span className="mx-mono" style={{ fontSize: 12 }}>{v || "—"}</span>} />
      </Table>
    </div>
  );
};
