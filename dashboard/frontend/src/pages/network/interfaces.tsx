import { useCallback, useEffect, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Select, Button, Space, Typography, Alert,
  Tooltip, Drawer, Form, Input, InputNumber, Switch, Segmented, Divider,
  Popconfirm, Modal, message as antdMessage,
} from "antd";
import {
  ApiOutlined, GlobalOutlined, PartitionOutlined, ReloadOutlined,
  DisconnectOutlined, ThunderboltOutlined, EditOutlined, TagOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";
import { derivePool, prefixToMask } from "./ipmath";

const { Text } = Typography;

type Iface = {
  interface: string;
  kind: "ethernet" | "vlan";
  description?: string;
  state?: string;
  carrier?: boolean | null;
  mac?: string;
  mtu?: number | null;
  addresses?: string[];
  configured?: boolean;
  present?: boolean;
  admin_enabled?: boolean;
  ipv4_mode?: "dhcp" | "static" | "none";
  static_addresses?: string[];
  gateway?: string | null;
  nameservers?: string[];
  role?: "wan" | "zone" | "unassigned";
  zone?: string | null;
  is_wan?: boolean;
  vlan_id?: number | null;
  parent?: string | null;
};

type Manage = { wan_iface: string; interfaces: Iface[] };

const roleTag = (i: Iface) => {
  if (i.role === "wan") return <Tag color="volcano" icon={<GlobalOutlined />}>WAN</Tag>;
  if (i.role === "zone") return <Tag color="blue" icon={<PartitionOutlined />}>{i.zone?.toUpperCase()}</Tag>;
  return <Tag>Livre</Tag>;
};

const stateTag = (i: Iface) => {
  // Estado administrativo (ligado/desligado pelo sistema)
  const adminTag = i.admin_enabled === false
    ? <Tag color="red" icon={<DisconnectOutlined />}>Desligada</Tag>
    : <Tag color="green" icon={<ThunderboltOutlined />}>Ligada</Tag>;
  
  // Estado físico (cabo conectado/desconectado)
  const linkTag = i.carrier === false
    ? <Tag color="orange">Sem cabo</Tag>
    : i.carrier === true
      ? <Tag color="blue">Cabo OK</Tag>
      : <Tag color="default">Link ?</Tag>;
  
  return <Space size={4}>{adminTag}{linkTag}</Space>;
};

const modeLabel: Record<string, string> = { dhcp: "DHCP", static: "Estático", none: "Sem IP" };

export const InterfacesPage = () => {
  const [data, setData] = useState<Manage | null>(null);
  const [pinned, setPinned] = useState<{ wan_iface: string; wan_pinned: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<Iface | null>(null);
  const [form] = Form.useForm();
  const [mode, setMode] = useState<"dhcp" | "static" | "none">("dhcp");
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, a] = await Promise.all([
        api.get<Manage>("/api/network/interfaces/manage"),
        api.get<{ wan_iface: string; wan_pinned: boolean }>("/api/network/assignments").catch(() => null),
      ]);
      setData(m.data);
      if (a) setPinned({ wan_iface: a.data.wan_iface, wan_pinned: a.data.wan_pinned });
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

  const toggleAdmin = async (i: Iface, enabled: boolean) => {
    try {
      await api.put(`/api/network/interfaces/${i.interface}`, { admin_enabled: enabled });
      msg.success(`${i.interface} ${enabled ? "habilitada" : "desabilitada"}`);
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao alterar estado");
    }
  };

  const openEdit = (i: Iface) => {
    setEditing(i);
    const m = i.ipv4_mode || "dhcp";
    setMode(m);
    form.setFieldsValue({
      description: i.description || "",
      admin_enabled: i.admin_enabled !== false,
      ipv4_mode: m,
      address: i.static_addresses?.[0] || "",
      gateway: i.gateway || "",
      nameservers: i.nameservers || [],
      mtu: i.mtu || undefined,
    });
  };

  // Product decision: DHCP comes up by default on the LAN. After a static IP
  // is saved on an interface with no zone, offer to create the 'lan' zone with
  // a default pool in the same flow (adjustable later in Rede › Zonas).
  const offerLanZone = (iface: string, cidr: string) => {
    const [ip, p] = (cidr || "").split("/");
    const mask = prefixToMask(Number(p));
    const pool = ip && mask ? derivePool(ip, mask) : null;
    if (!ip || !mask || !pool) return; // can't derive a sane pool — skip the offer
    Modal.confirm({
      title: `Criar zona 'lan' em ${iface}?`,
      content: `IP estático salvo. Subir DHCP padrão nesta rede (pool ${pool[0]} → ${pool[1]}, gateway ${ip})? Você pode ajustar ou desativar depois em Rede › Zonas.`,
      okText: "Criar zona",
      cancelText: "Agora não",
      onOk: async () => {
        try {
          await api.post("/api/network/zones", {
            zone: "lan",
            interface: iface,
            listen_address: ip,
            gateway: ip,
            netmask: mask,
            dhcp_start: pool[0],
            dhcp_end: pool[1],
          });
          msg.success("Zona 'lan' criada — DHCP ativo nesta interface");
          load();
        } catch (e: any) {
          msg.error(e?.response?.data?.detail || "Falha ao criar a zona");
        }
      },
    });
  };

  const submitEdit = async () => {
    if (!editing) return;
    const v = await form.validateFields();
    setSaving(true);
    try {
      await api.put(`/api/network/interfaces/${editing.interface}`, {
        description: v.description,
        admin_enabled: v.admin_enabled,
        ipv4_mode: v.ipv4_mode,
        address: v.ipv4_mode === "static" ? v.address : null,
        gateway: v.ipv4_mode === "static" ? v.gateway || null : null,
        nameservers: v.nameservers || [],
        mtu: v.mtu || null,
      });
      msg.success(`${editing.interface} atualizada`);
      const noZone = editing.role !== "zone" && editing.role !== "wan" && !editing.is_wan;
      setEditing(null);
      load();
      if (v.ipv4_mode === "static" && noZone) {
        offerLanZone(editing.interface, v.address);
      }
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao salvar (revertido)");
    } finally {
      setSaving(false);
    }
  };

  const ifaces = data?.interfaces || [];
  const upCount = ifaces.filter((i) => i.state === "up").length;
  const zoneCount = ifaces.filter((i) => i.role === "zone").length;
  const vlanCount = ifaces.filter((i) => i.kind === "vlan").length;
  const wanOptions = ifaces
    .filter((i) => i.kind === "ethernet")
    .map((i) => ({
      value: i.interface,
      label: `${i.interface}${i.addresses?.[0] ? ` · ${i.addresses[0]}` : ""}${i.state !== "up" ? ` · ${i.state}` : ""}`,
    }));

  return (
    <div>
      {ctx}
      <PageHeader
        eyebrow={<><ApiOutlined /> Hardware de rede</>}
        title="Interfaces"
        subtitle="Detecção automática das placas deste appliance, com configuração profissional e persistente (netplan): apelido, habilitar/desabilitar, IPv4 (DHCP/estático), gateway, MTU e atribuição de papéis. Adapta-se a qualquer hardware."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} md={6}><KpiCard icon={<ApiOutlined />} color="#1677ff" label="Interfaces" value={ifaces.length} /></Col>
        <Col xs={12} md={6}><KpiCard icon={<ThunderboltOutlined />} color="#52c41a" label="Ativas (up)" value={upCount} /></Col>
        <Col xs={12} md={6}><KpiCard icon={<PartitionOutlined />} color="#722ed1" label="Em zonas" value={zoneCount} /></Col>
        <Col xs={12} md={6}><KpiCard icon={<TagOutlined />} color="#fa8c16" label="VLANs" value={vlanCount} /></Col>
      </Row>

      <Card bordered={false} className="mx-card" style={{ marginBottom: 16 }}
        title={<><GlobalOutlined /> Interface WAN (uplink / Internet)</>}>
        <Row gutter={16} align="middle">
          <Col xs={24} md={14}>
            <Text type="secondary">
              A WAN é a interface conectada à Internet. Por padrão é detectada pela rota
              default. Ao fixá-la, todas as regras de NAT e de zona passam a segui-la
              automaticamente.
            </Text>
          </Col>
          <Col xs={24} md={10}>
            <Space wrap>
              <Select
                style={{ minWidth: 240 }}
                value={pinned?.wan_pinned ? pinned?.wan_iface : undefined}
                placeholder={pinned ? `Auto: ${pinned.wan_iface || "—"}` : "…"}
                options={wanOptions}
                onChange={setWan}
                loading={saving}
                showSearch
                optionFilterProp="label"
              />
              <Tooltip title="Voltar para detecção automática (rota default)">
                <Button onClick={() => setWan("")} disabled={!pinned?.wan_pinned || saving}>Auto</Button>
              </Tooltip>
            </Space>
            <div style={{ marginTop: 8 }}>
              {pinned && (
                <Tag color={pinned.wan_pinned ? "volcano" : "green"}>
                  {pinned.wan_pinned ? `Fixada: ${pinned.wan_iface}` : `Automática: ${pinned.wan_iface || "indefinida"}`}
                </Tag>
              )}
            </div>
          </Col>
        </Row>
      </Card>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="Como tudo se conecta"
        description="As interfaces detectadas aqui podem ser configuradas (IP, MTU, habilitação) e usadas como base de VLANs (Rede › VLANs). Cada interface ou VLAN com DHCP/DNS vira uma zona em Rede › Zonas. Alterações são validadas e aplicadas via netplan, com backup e rollback automático." />

      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>Atualizar</Button>
      </Space>

      <Table dataSource={ifaces} rowKey="interface" loading={loading} size="middle" pagination={false}>
        <Table.Column title="Interface" dataIndex="interface" width={170}
          render={(v, r: Iface) => (
            <Space direction="vertical" size={0}>
              <Space>
                {r.kind === "vlan"
                  ? <TagOutlined style={{ color: "#fa8c16" }} />
                  : <ApiOutlined style={{ color: "#1677ff" }} />}
                <span className="mx-mono">{v}</span>
                {r.kind === "vlan" && <Tag color="orange">VLAN {r.vlan_id}</Tag>}
              </Space>
              {r.description ? <Text type="secondary" style={{ fontSize: 12 }}>{r.description}</Text> : null}
              {r.kind === "vlan" && r.parent
                ? <Text type="secondary" style={{ fontSize: 12 }}>sobre {r.parent}</Text> : null}
            </Space>
          )} />
        <Table.Column title="Papel" width={120} render={(_, r: Iface) => roleTag(r)} />
        <Table.Column title="Estado" width={120} render={(_, r: Iface) => stateTag(r)} />
        <Table.Column title="IPv4" width={110}
          render={(_, r: Iface) => <Tag>{modeLabel[r.ipv4_mode || "none"]}</Tag>} />
        <Table.Column title="Endereço(s)" render={(_, r: Iface) =>
          r.addresses && r.addresses.length
            ? <Space direction="vertical" size={0}>
                {r.addresses.map((a) => <span key={a} className="mx-mono">{a}</span>)}
                {r.gateway ? <Text type="secondary" style={{ fontSize: 12 }}>gw <span className="mx-mono">{r.gateway}</span></Text> : null}
              </Space>
            : <Text type="secondary">sem IP</Text>} />
        <Table.Column title="MTU" dataIndex="mtu" width={80}
          render={(v) => <span className="mx-mono">{v || "—"}</span>} />
        <Table.Column title="Habilitada" width={100} render={(_, r: Iface) => (
          <Tooltip title={r.is_wan ? "A WAN ativa não pode ser desabilitada" : undefined}>
            <Switch size="small" checked={r.admin_enabled !== false} disabled={r.is_wan}
              onChange={(c) => toggleAdmin(r, c)} />
          </Tooltip>
        )} />
        <Table.Column title="Ações" width={90} render={(_, r: Iface) => (
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>Editar</Button>
        )} />
      </Table>

      <Drawer
        title={editing ? <Space><EditOutlined /> Configurar {editing.interface}</Space> : ""}
        width={460} open={!!editing} onClose={() => setEditing(null)}
        extra={<Button type="primary" loading={saving} onClick={submitEdit}>Salvar</Button>}
      >
        {editing?.is_wan && (
          <Alert type="warning" showIcon style={{ marginBottom: 16 }}
            message="Interface WAN ativa"
            description="Esta interface carrega o uplink da Internet. Para evitar lockout, ela não pode ser desabilitada nem ficar sem IP/gateway." />
        )}
        <Form form={form} layout="vertical">
          <Form.Item name="description" label="Apelido (nome amigável)"
            tooltip="Descrição exibida no painel, como WAN, LAN, Servidores. Não altera o nome do kernel.">
            <Input placeholder="ex.: LAN Escritório" maxLength={64} />
          </Form.Item>
          <Form.Item name="admin_enabled" label="Habilitada" valuePropName="checked">
            <Switch disabled={editing?.is_wan} />
          </Form.Item>
          <Divider plain>Endereçamento IPv4</Divider>
          <Form.Item name="ipv4_mode" label="Modo">
            <Segmented
              options={[
                { label: "DHCP", value: "dhcp" },
                { label: "Estático", value: "static" },
                { label: "Sem IP", value: "none" },
              ]}
              onChange={(v) => setMode(v as any)}
            />
          </Form.Item>
          {mode === "static" && (
            <>
              <Form.Item name="address" label="Endereço / CIDR"
                rules={[{ required: true, message: "Informe o IP/CIDR" },
                  { pattern: /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/, message: "ex.: 192.168.10.1/24" }]}>
                <Input placeholder="192.168.10.1/24" className="mx-mono" />
              </Form.Item>
              <Form.Item name="gateway" label="Gateway"
                tooltip="Necessário apenas se esta interface fornecer a rota default (geralmente só a WAN).">
                <Input placeholder="192.168.10.254 (opcional)" className="mx-mono" />
              </Form.Item>
              <Form.Item name="nameservers" label="Servidores DNS">
                <Select mode="tags" tokenSeparators={[",", " "]} placeholder="1.1.1.1, 8.8.8.8" className="mx-mono" />
              </Form.Item>
            </>
          )}
          <Divider plain>Avançado</Divider>
          <Form.Item name="mtu" label="MTU" tooltip="Tamanho máximo do quadro (576–9216). Padrão 1500.">
            <InputNumber min={576} max={9216} style={{ width: "100%" }} placeholder="1500" />
          </Form.Item>
        </Form>
        {editing && !editing.is_wan && (
          <Popconfirm title="Restaurar para DHCP automático?"
            onConfirm={() => { form.setFieldsValue({ ipv4_mode: "dhcp" }); setMode("dhcp"); }}>
            <Button type="link" style={{ paddingLeft: 0 }}>Restaurar para DHCP</Button>
          </Popconfirm>
        )}
      </Drawer>
    </div>
  );
};
