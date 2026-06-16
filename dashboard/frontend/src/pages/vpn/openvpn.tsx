import { useCallback, useEffect, useRef, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Button, Space, Typography, Alert,
  Form, Input, InputNumber, Switch, Select, Modal, message as antdMessage, Popconfirm,
} from "antd";
import {
  SafetyCertificateOutlined, ReloadOutlined, PlusOutlined, EditOutlined,
  GlobalOutlined, CheckCircleFilled, CloseCircleFilled, DownloadOutlined,
  KeyOutlined, TeamOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text } = Typography;

type Client = {
  id?: string;
  name: string;
  cn?: string;
  type: "roadwarrior" | "site";
  enabled: boolean;
  site_subnets: string[];
  has_cert?: boolean;
  real_address?: string;
  rx_bytes?: number;
  tx_bytes?: number;
  online?: boolean;
};

type Status = {
  enabled: boolean;
  proto: "udp" | "tcp";
  port: number;
  subnet: string;
  dev: string;
  dns: string;
  full_tunnel: boolean;
  endpoint_host: string;
  effective_endpoint: string | null;
  pki_ready: boolean;
  unit_active: boolean;
  wan_iface: string | null;
  clients: Client[];
};

const blankClient: Client = {
  name: "",
  type: "roadwarrior",
  enabled: true,
  site_subnets: [],
};

function fmtBytes(n?: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function OpenVpnPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [proto, setProto] = useState<"udp" | "tcp">("udp");
  const [port, setPort] = useState(1194);
  const [subnet, setSubnet] = useState("10.21.0.0/24");
  const [dns, setDns] = useState("");
  const [fullTunnel, setFullTunnel] = useState(true);
  const [endpointHost, setEndpointHost] = useState("");
  const [editing, setEditing] = useState<Client | null>(null);
  const [form] = Form.useForm();
  const dirtyRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<{ openvpn: Status }>("/api/vpn/status");
      const ov = r.data.openvpn;
      setStatus(ov);
      if (!dirtyRef.current) {
        setEnabled(ov.enabled);
        setProto(ov.proto);
        setPort(ov.port);
        setSubnet(ov.subnet);
        setDns(ov.dns);
        setFullTunnel(ov.full_tunnel);
        setEndpointHost(ov.endpoint_host);
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
      await api.put("/api/vpn/openvpn", {
        enabled, proto, port, subnet, dns,
        full_tunnel: fullTunnel, endpoint_host: endpointHost,
      });
      dirtyRef.current = false;
      antdMessage.success("OpenVPN aplicado");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao aplicar");
    } finally {
      setSaving(false);
    }
  };

  const openEditor = (c: Client | null) => {
    const data = c ? { ...c } : { ...blankClient };
    setEditing(data);
    form.setFieldsValue({ ...data, site_subnets: (data.site_subnets || []).join(", ") });
  };

  const submitClient = async () => {
    const vals = await form.validateFields();
    const subnets = String(vals.site_subnets || "")
      .split(/[,\s]+/).map((s: string) => s.trim()).filter(Boolean);
    try {
      await api.post("/api/vpn/openvpn/clients", {
        id: editing?.id, name: vals.name, type: vals.type,
        enabled: vals.enabled, site_subnets: subnets,
      });
      antdMessage.success("Cliente salvo");
      setEditing(null);
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar cliente");
    }
  };

  const removeClient = async (id?: string) => {
    if (!id) return;
    try {
      await api.delete(`/api/vpn/openvpn/clients/${id}`);
      antdMessage.success("Cliente revogado");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao revogar");
    }
  };

  const downloadConfig = async (c: Client) => {
    try {
      const r = await api.get(`/api/vpn/openvpn/clients/${c.id}/config`, {
        responseType: "text",
      });
      const blob = new Blob([r.data as any], { type: "application/x-openvpn-profile" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(c.cn || c.name).replace(/[^A-Za-z0-9_-]/g, "_")}.ovpn`;
      a.click();
      URL.revokeObjectURL(url);
      if (!status?.enabled || !status?.unit_active) {
        antdMessage.warning(
          'Perfil .ovpn gerado, mas o servidor OpenVPN ainda não está ativo — ative o OpenVPN e clique em "Aplicar" para que o cliente consiga conectar.',
          6,
        );
      } else {
        antdMessage.success(`Perfil de ${c.name} baixado`);
      }
      load(true);
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao gerar o perfil .ovpn");
    }
  };

  const clients = status?.clients || [];
  const online = clients.filter((c) => c.online).length;

  const columns = [
    {
      title: "Estado",
      key: "state",
      width: 90,
      render: (_: any, c: Client) => {
        if (!enabled || !c.enabled) return <Tag>—</Tag>;
        return c.online
          ? <Tag icon={<CheckCircleFilled />} color="success">online</Tag>
          : <Tag icon={<CloseCircleFilled />} color="default">offline</Tag>;
      },
    },
    {
      title: "Nome",
      dataIndex: "name",
      render: (v: string, c: Client) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Space size={4}>
            <Tag color={c.type === "site" ? "purple" : "blue"}>
              {c.type === "site" ? "site-to-site" : "road-warrior"}
            </Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>CN {c.cn}</Text>
          </Space>
        </Space>
      ),
    },
    {
      title: "Rede / tráfego",
      key: "net",
      render: (_: any, c: Client) =>
        c.type === "site" && c.site_subnets?.length > 0 ? (
          <Text type="secondary" style={{ fontSize: 12 }}>→ {c.site_subnets.join(", ")}</Text>
        ) : enabled && c.online ? (
          <Space direction="vertical" size={0}>
            <Text code>{c.real_address}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ↓{fmtBytes(c.rx_bytes)} ↑{fmtBytes(c.tx_bytes)}
            </Text>
          </Space>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: "",
      key: "actions",
      width: 180,
      render: (_: any, c: Client) => (
        <Space wrap>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => downloadConfig(c)}>
            .ovpn
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(c)} />
          <Popconfirm title="Revogar e remover este cliente?" onConfirm={() => removeClient(c.id)}>
            <Button size="small" danger>Revogar</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="VPN"
        title="OpenVPN"
        subtitle="Servidor OpenVPN — acesso remoto e site-to-site, com PKI por cliente"
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
        description="O OpenVPN é desligado por padrão. Ao ativar, o appliance gera uma PKI própria (certificados EC por cliente) e protege o canal de controle com tls-crypt. Cada cliente recebe um arquivo .ovpn pronto (com certificados embutidos). Revogar um cliente invalida o certificado dele via CRL, mesmo que ele mantenha a chave."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<TeamOutlined />} color="#6366f1" label="Clientes" value={clients.length} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CheckCircleFilled />} color="#22c55e" label="Online" value={enabled ? online : "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<SafetyCertificateOutlined />} color="#f59e0b" label="Serviço"
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
              <Text strong>{enabled ? "OpenVPN ATIVO" : "OpenVPN desligado"}</Text>
              {status && enabled !== status.enabled && (
                <Tag color="warning">não aplicado</Tag>
              )}
            </Space>
          </Col>
          <Col xs={12} md={4}>
            <Text type="secondary">Protocolo</Text>
            <Select style={{ width: "100%" }} value={proto}
              onChange={(v) => { setProto(v); markDirty(); }}
              options={[{ value: "udp", label: "UDP" }, { value: "tcp", label: "TCP" }]} />
          </Col>
          <Col xs={12} md={4}>
            <Text type="secondary">Porta</Text>
            <InputNumber style={{ width: "100%" }} min={1} max={65535} value={port}
              onChange={(v) => { setPort(Number(v)); markDirty(); }} />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary">Rede dos clientes (CIDR)</Text>
            <Input value={subnet} onChange={(e) => { setSubnet(e.target.value); markDirty(); }} />
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
          <Col xs={12} md={8}>
            <Space>
              <Switch checked={fullTunnel} onChange={(v) => { setFullTunnel(v); markDirty(); }} />
              <Text type="secondary">Túnel completo (redireciona todo o tráfego)</Text>
            </Space>
          </Col>
        </Row>
        {status && enabled !== status.enabled && (
          <Alert style={{ marginTop: 12 }} type="warning" showIcon
            message='Alterações não aplicadas'
            description='Clique em "Aplicar" para que a mudança tenha efeito. Enquanto não aplicar, o serviço continua no estado anterior.' />
        )}
        {status && !status.pki_ready && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon
            message="A PKI será criada automaticamente ao ativar o OpenVPN ou ao baixar o primeiro .ovpn." />
        )}
      </Card>

      <Card
        title={<Space><TeamOutlined />Clientes</Space>}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>Novo cliente</Button>}
      >
        <Table rowKey="id" size="small" loading={loading} dataSource={clients} columns={columns as any}
          pagination={false} locale={{ emptyText: "Nenhum cliente cadastrado" }} />
      </Card>

      {editing && (
        <Modal
          open
          title={editing?.id ? "Editar cliente" : "Novo cliente"}
          onCancel={() => setEditing(null)}
          onOk={submitClient}
          okText="Salvar"
          destroyOnClose
        >
          <Form form={form} layout="vertical" preserve={false}>
            <Form.Item name="name" label="Nome" rules={[{ required: true }]}>
              <Input placeholder="ex: notebook-joao ou filial-rj" />
            </Form.Item>
            <Form.Item name="type" label="Tipo" initialValue="roadwarrior">
              <Select options={[
                { value: "roadwarrior", label: "Road-warrior (cliente remoto)" },
                { value: "site", label: "Site-to-site (rede remota)" },
              ]} />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(p, c) => p.type !== c.type}>
              {({ getFieldValue }) =>
                getFieldValue("type") === "site" ? (
                  <Form.Item name="site_subnets" label="Sub-redes remotas (vírgula)"
                    rules={[{ required: true, message: "informe ao menos uma sub-rede" }]}>
                    <Input placeholder="192.168.70.0/24, 10.0.0.0/24" />
                  </Form.Item>
                ) : null
              }
            </Form.Item>
            <Form.Item name="enabled" label="Ativo" valuePropName="checked" initialValue={true}>
              <Switch />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  );
}
