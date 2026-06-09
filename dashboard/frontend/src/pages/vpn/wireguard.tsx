import { useCallback, useEffect, useRef, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Button, Space, Typography, Alert,
  Form, Input, InputNumber, Switch, Select, Divider, Modal, Popconfirm,
  message as antdMessage,
} from "antd";
import {
  SafetyCertificateOutlined, ReloadOutlined, PlusOutlined, EditOutlined,
  GlobalOutlined, CheckCircleFilled, CloseCircleFilled, QrcodeOutlined,
  DownloadOutlined, KeyOutlined, TeamOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text, Paragraph } = Typography;

type Peer = {
  id?: string;
  name: string;
  type: "roadwarrior" | "site";
  enabled: boolean;
  address: string;
  public_key?: string;
  site_subnets: string[];
  endpoint: string;
  keepalive?: number;
  full_tunnel: boolean;
  has_private_key?: boolean;
  live_endpoint?: string;
  last_handshake?: number;
  rx_bytes?: number;
  tx_bytes?: number;
  online?: boolean;
};

type Status = {
  enabled: boolean;
  interface: string;
  listen_port: number;
  address: string;
  dns: string;
  endpoint_host: string;
  effective_endpoint: string | null;
  mtu: number;
  public_key: string;
  unit_active: boolean;
  wan_iface: string | null;
  peers: Peer[];
};

const blankPeer: Peer = {
  name: "",
  type: "roadwarrior",
  enabled: true,
  address: "",
  site_subnets: [],
  endpoint: "",
  keepalive: 25,
  full_tunnel: true,
};

function fmtBytes(n?: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtHandshake(ts?: number): string {
  if (!ts) return "nunca";
  const secs = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (secs < 60) return `há ${secs}s`;
  if (secs < 3600) return `há ${Math.floor(secs / 60)}min`;
  return `há ${Math.floor(secs / 3600)}h`;
}

export function WireGuardPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [iface, setIface] = useState("wg0");
  const [port, setPort] = useState(51820);
  const [address, setAddress] = useState("10.20.0.1/24");
  const [dns, setDns] = useState("");
  const [endpointHost, setEndpointHost] = useState("");
  const [mtu, setMtu] = useState(1420);
  const [editing, setEditing] = useState<Peer | null>(null);
  const [qr, setQr] = useState<{ name: string; img: string } | null>(null);
  const [form] = Form.useForm();
  const dirtyRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<{ wireguard: Status }>("/api/vpn/status");
      const wg = r.data.wireguard;
      setStatus(wg);
      if (!dirtyRef.current) {
        setEnabled(wg.enabled);
        setIface(wg.interface);
        setPort(wg.listen_port);
        setAddress(wg.address);
        setDns(wg.dns);
        setEndpointHost(wg.endpoint_host);
        setMtu(wg.mtu);
      }
    } catch {
      /* ignore */
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(() => load(true), 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const markDirty = () => { dirtyRef.current = true; };

  const saveServer = async () => {
    setSaving(true);
    try {
      await api.put("/api/vpn/wireguard", {
        enabled, interface: iface, listen_port: port, address,
        dns, endpoint_host: endpointHost, mtu,
      });
      dirtyRef.current = false;
      antdMessage.success("WireGuard aplicado");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao aplicar");
    } finally {
      setSaving(false);
    }
  };

  const openEditor = (p: Peer | null) => {
    const data = p ? { ...p } : { ...blankPeer };
    setEditing(data);
    form.setFieldsValue({
      ...data,
      site_subnets: (data.site_subnets || []).join(", "),
    });
  };

  const submitPeer = async () => {
    const vals = await form.validateFields();
    const subnets = String(vals.site_subnets || "")
      .split(/[,\s]+/).map((s: string) => s.trim()).filter(Boolean);
    const body: any = {
      id: editing?.id,
      name: vals.name,
      type: vals.type,
      enabled: vals.enabled,
      address: vals.address || "",
      public_key: vals.public_key || "",
      site_subnets: subnets,
      endpoint: vals.endpoint || "",
      keepalive: vals.keepalive ?? 25,
      full_tunnel: vals.full_tunnel,
    };
    try {
      await api.post("/api/vpn/wireguard/peers", body);
      antdMessage.success("Peer salvo");
      setEditing(null);
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar peer");
    }
  };

  const removePeer = async (id?: string) => {
    if (!id) return;
    try {
      await api.delete(`/api/vpn/wireguard/peers/${id}`);
      antdMessage.success("Peer removido");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao remover");
    }
  };

  const downloadConfig = async (p: Peer) => {
    try {
      const r = await api.get(`/api/vpn/wireguard/peers/${p.id}/config`, {
        responseType: "text",
      });
      const blob = new Blob([r.data as any], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${p.name.replace(/[^A-Za-z0-9_-]/g, "_")}.conf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Sem configuração exportável");
    }
  };

  const showQr = async (p: Peer) => {
    try {
      const r = await api.get<{ qr: string }>(`/api/vpn/wireguard/peers/${p.id}/qr`);
      setQr({ name: p.name, img: r.data.qr });
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Sem QR (peer com chave externa)");
    }
  };

  const peers = status?.peers || [];
  const online = peers.filter((p) => p.online).length;

  const columns = [
    {
      title: "Estado",
      key: "state",
      width: 90,
      render: (_: any, p: Peer) => {
        if (!enabled || !p.enabled) return <Tag>—</Tag>;
        return p.online
          ? <Tag icon={<CheckCircleFilled />} color="success">online</Tag>
          : <Tag icon={<CloseCircleFilled />} color="default">offline</Tag>;
      },
    },
    {
      title: "Nome",
      dataIndex: "name",
      render: (v: string, p: Peer) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Tag color={p.type === "site" ? "purple" : "blue"} style={{ marginTop: 2 }}>
            {p.type === "site" ? "site-to-site" : "road-warrior"}
          </Tag>
        </Space>
      ),
    },
    {
      title: "Endereço túnel",
      dataIndex: "address",
      render: (v: string, p: Peer) => (
        <Space direction="vertical" size={0}>
          <Text code>{v}</Text>
          {p.type === "site" && p.site_subnets?.length > 0 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              → {p.site_subnets.join(", ")}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: "Handshake",
      key: "hs",
      render: (_: any, p: Peer) =>
        enabled && p.enabled ? (
          <Space direction="vertical" size={0}>
            <Text>{fmtHandshake(p.last_handshake)}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ↓{fmtBytes(p.rx_bytes)} ↑{fmtBytes(p.tx_bytes)}
            </Text>
          </Space>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: "",
      key: "actions",
      width: 220,
      render: (_: any, p: Peer) => (
        <Space wrap>
          {p.has_private_key && (
            <>
              <Button size="small" icon={<QrcodeOutlined />} onClick={() => showQr(p)} />
              <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadConfig(p)} />
            </>
          )}
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(p)} />
          <Popconfirm title="Remover peer?" onConfirm={() => removePeer(p.id)}>
            <Button size="small" danger>Remover</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="VPN"
        title="WireGuard"
        subtitle="Servidor/concentrador VPN — acesso remoto (road-warrior) e site-to-site"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
              Atualizar
            </Button>
            <Button type="primary" onClick={saveServer} loading={saving}>
              Aplicar
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Subsistema isolado e opcional"
        description="O WireGuard é desligado por padrão. Ao ativar, o appliance vira servidor VPN: clientes road-warrior (notebooks/celulares) e túneis site-to-site conectam de fora. As portas e o encaminhamento são abertos automaticamente no firewall (anti-lockout preservado). Chaves são geradas no appliance; exporte a configuração ou o QR para cada cliente."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<TeamOutlined />} color="#6366f1" label="Peers" value={peers.length} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CheckCircleFilled />} color="#22c55e" label="Online" value={enabled ? online : "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<SafetyCertificateOutlined />} color="#f59e0b" label="Túnel"
            value={status?.unit_active ? "ativo" : "parado"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<GlobalOutlined />} color="#0ea5e9" label="Endpoint"
            value={status?.effective_endpoint || "—"} />
        </Col>
      </Row>

      <Card style={{ marginBottom: 16 }} title={<Space><KeyOutlined />Servidor</Space>}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} md={8}>
            <Space>
              <Switch checked={enabled} onChange={(v) => { setEnabled(v); markDirty(); }} />
              <Text strong>{enabled ? "WireGuard ATIVO" : "WireGuard desligado"}</Text>
            </Space>
          </Col>
          <Col xs={12} md={4}>
            <Text type="secondary">Interface</Text>
            <Input value={iface} onChange={(e) => { setIface(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={4}>
            <Text type="secondary">Porta (UDP)</Text>
            <InputNumber style={{ width: "100%" }} min={1} max={65535} value={port}
              onChange={(v) => { setPort(Number(v)); markDirty(); }} />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary">Rede do túnel (CIDR)</Text>
            <Input value={address} onChange={(e) => { setAddress(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={24} md={8}>
            <Text type="secondary">Host público (endpoint) — vazio = IP da WAN</Text>
            <Input value={endpointHost} placeholder={status?.wan_iface ? "auto (WAN)" : ""}
              onChange={(e) => { setEndpointHost(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary">DNS para clientes (opcional)</Text>
            <Input value={dns} placeholder="192.168.1.1"
              onChange={(e) => { setDns(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={4}>
            <Text type="secondary">MTU</Text>
            <InputNumber style={{ width: "100%" }} min={1280} max={1500} value={mtu}
              onChange={(v) => { setMtu(Number(v)); markDirty(); }} />
          </Col>
        </Row>
        {status?.public_key && (
          <>
            <Divider style={{ margin: "16px 0" }} />
            <Text type="secondary">Chave pública do servidor: </Text>
            <Text code copyable>{status.public_key}</Text>
          </>
        )}
      </Card>

      <Card
        title={<Space><TeamOutlined />Peers</Space>}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>Novo peer</Button>}
      >
        <Table rowKey="id" size="small" loading={loading} dataSource={peers} columns={columns as any}
          pagination={false} locale={{ emptyText: "Nenhum peer cadastrado" }} />
      </Card>

      <Modal
        open={!!editing}
        title={editing?.id ? "Editar peer" : "Novo peer"}
        onCancel={() => setEditing(null)}
        onOk={submitPeer}
        okText="Salvar"
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="Nome" rules={[{ required: true }]}>
            <Input placeholder="ex: notebook-joao ou filial-sp" />
          </Form.Item>
          <Form.Item name="type" label="Tipo" initialValue="roadwarrior">
            <Select
              options={[
                { value: "roadwarrior", label: "Road-warrior (cliente remoto)" },
                { value: "site", label: "Site-to-site (rede remota)" },
              ]}
            />
          </Form.Item>
          <Form.Item name="address" label="Endereço do túnel (vazio = automático)"
            tooltip="IP do peer na rede do túnel, ex: 10.20.0.2/32">
            <Input placeholder="auto" />
          </Form.Item>
          <Form.Item name="public_key"
            label="Chave pública (vazio = o appliance gera o par e permite exportar config/QR)"
            tooltip="Informe para 'traga sua própria chave' (a privada nunca fica no appliance)">
            <Input placeholder="auto-gerar" />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.type !== c.type}>
            {({ getFieldValue }) =>
              getFieldValue("type") === "site" ? (
                <>
                  <Form.Item name="site_subnets" label="Sub-redes remotas (vírgula)"
                    rules={[{ required: true, message: "informe ao menos uma sub-rede" }]}>
                    <Input placeholder="192.168.50.0/24, 10.0.0.0/24" />
                  </Form.Item>
                  <Form.Item name="endpoint" label="Endpoint remoto (opcional, host:porta)"
                    tooltip="Preencha se o appliance deve discar para o outro lado">
                    <Input placeholder="200.1.2.3:51820" />
                  </Form.Item>
                </>
              ) : (
                <Form.Item name="full_tunnel" label="Túnel completo (todo o tráfego do cliente)"
                  valuePropName="checked" initialValue={true}>
                  <Switch />
                </Form.Item>
              )
            }
          </Form.Item>
          <Form.Item name="keepalive" label="Keepalive (s)" initialValue={25}>
            <InputNumber min={0} max={600} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="enabled" label="Ativo" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal open={!!qr} title={`QR — ${qr?.name || ""}`} footer={null} onCancel={() => setQr(null)}>
        <Paragraph type="secondary">
          Abra o app WireGuard no celular, toque em "+" → "Ler QR code".
        </Paragraph>
        {qr && (
          <img src={qr.img} alt="QR WireGuard"
            style={{ width: "100%", maxWidth: 320, display: "block", margin: "0 auto" }} />
        )}
      </Modal>
    </div>
  );
}
