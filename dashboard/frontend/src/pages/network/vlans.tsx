import { useCallback, useEffect, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Button, Space, Typography, Alert, Modal, Form,
  Input, InputNumber, Select, Segmented, Divider, Popconfirm,
  message as antdMessage,
} from "antd";
import {
  TagOutlined, PlusOutlined, ReloadOutlined, DeleteOutlined, ApiOutlined,
  PartitionOutlined, ThunderboltOutlined, DisconnectOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text } = Typography;

type Iface = {
  interface: string;
  kind: "ethernet" | "vlan";
  description?: string;
  state?: string;
  admin_enabled?: boolean;
  ipv4_mode?: "dhcp" | "static" | "none";
  addresses?: string[];
  gateway?: string | null;
  role?: string;
  zone?: string | null;
  vlan_id?: number | null;
  parent?: string | null;
};

const modeLabel: Record<string, string> = { dhcp: "DHCP", static: "Estático", none: "Sem IP" };

export const VlansPage = () => {
  const [vlans, setVlans] = useState<Iface[]>([]);
  const [parents, setParents] = useState<Iface[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"dhcp" | "static" | "none">("none");
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{ wan_iface: string; interfaces: Iface[] }>(
        "/api/network/interfaces/manage");
      setVlans(data.interfaces.filter((i) => i.kind === "vlan"));
      setParents(data.interfaces.filter((i) => i.kind === "ethernet"));
    } catch {
      msg.error("Falha ao carregar VLANs");
    } finally {
      setLoading(false);
    }
  }, [msg]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    form.resetFields();
    setMode("none");
    form.setFieldsValue({ ipv4_mode: "none" });
    setOpen(true);
  };

  const submit = async () => {
    const v = await form.validateFields();
    setSaving(true);
    try {
      await api.post("/api/network/vlans", {
        parent: v.parent,
        vlan_id: v.vlan_id,
        name: v.name || null,
        description: v.description || "",
        ipv4_mode: v.ipv4_mode,
        address: v.ipv4_mode === "static" ? v.address : null,
        gateway: v.ipv4_mode === "static" ? v.gateway || null : null,
        nameservers: v.nameservers || [],
        mtu: v.mtu || null,
      });
      msg.success("VLAN criada");
      setOpen(false);
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao criar VLAN");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (name: string) => {
    try {
      await api.delete(`/api/network/vlans/${name}`);
      msg.success(`VLAN ${name} removida`);
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao remover VLAN");
    }
  };

  const parentOptions = parents.map((p) => ({
    value: p.interface,
    label: `${p.interface}${p.description ? ` · ${p.description}` : ""}${p.role === "wan" ? " (WAN)" : ""}`,
  }));

  return (
    <div>
      {ctx}
      <PageHeader
        eyebrow={<><TagOutlined /> Rede · Segmentação 802.1Q</>}
        title="VLANs"
        subtitle="Crie redes virtuais com tag 802.1Q sobre uma interface física. Cada VLAN vira uma sub-interface que pode receber IP e ser usada como zona (DHCP/DNS) e nas regras de firewall."
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>Nova VLAN</Button>}
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} md={8}><KpiCard icon={<TagOutlined />} color="#fa8c16" label="VLANs" value={vlans.length} /></Col>
        <Col xs={12} md={8}><KpiCard icon={<ThunderboltOutlined />} color="#52c41a" label="Ativas" value={vlans.filter((v) => v.state === "up").length} /></Col>
        <Col xs={12} md={8}><KpiCard icon={<ApiOutlined />} color="#1677ff" label="Interfaces pai" value={parents.length} /></Col>
      </Row>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="O que é uma VLAN?"
        description="Uma VLAN (802.1Q) separa logicamente várias redes sobre o mesmo cabo/placa física, identificadas por um número (tag) de 1 a 4094. É a forma profissional de segmentar a rede (ex.: VLAN 10 = Funcionários, VLAN 20 = Convidados, VLAN 30 = IoT) sem precisar de uma placa para cada uma." />

      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>Atualizar</Button>
      </Space>

      <Card bordered={false} className="mx-card">
        <Table dataSource={vlans} rowKey="interface" loading={loading} size="middle" pagination={false}
          locale={{ emptyText: "Nenhuma VLAN criada ainda. Clique em “Nova VLAN”." }}>
          <Table.Column title="VLAN" dataIndex="interface" width={200}
            render={(v, r: Iface) => (
              <Space direction="vertical" size={0}>
                <Space><TagOutlined style={{ color: "#fa8c16" }} />
                  <span className="mx-mono">{v}</span>
                  <Tag color="orange">tag {r.vlan_id}</Tag></Space>
                {r.description ? <Text type="secondary" style={{ fontSize: 12 }}>{r.description}</Text> : null}
              </Space>
            )} />
          <Table.Column title="Interface pai" dataIndex="parent" width={150}
            render={(p) => <Space><ApiOutlined style={{ color: "#1677ff" }} /><span className="mx-mono">{p || "—"}</span></Space>} />
          <Table.Column title="Zona" width={120} render={(_, r: Iface) =>
            r.role === "zone" ? <Tag color="blue" icon={<PartitionOutlined />}>{r.zone?.toUpperCase()}</Tag> : <Tag>Livre</Tag>} />
          <Table.Column title="Estado" width={110} render={(_, r: Iface) =>
            r.admin_enabled === false ? <Tag icon={<DisconnectOutlined />}>desabilitada</Tag>
              : r.state === "up" ? <Tag color="green" icon={<ThunderboltOutlined />}>up</Tag>
                : <Tag icon={<DisconnectOutlined />}>{r.state || "?"}</Tag>} />
          <Table.Column title="IPv4" width={100} render={(_, r: Iface) => <Tag>{modeLabel[r.ipv4_mode || "none"]}</Tag>} />
          <Table.Column title="Endereço(s)" render={(_, r: Iface) =>
            r.addresses && r.addresses.length
              ? <Space direction="vertical" size={0}>{r.addresses.map((a) => <span key={a} className="mx-mono">{a}</span>)}</Space>
              : <Text type="secondary">sem IP</Text>} />
          <Table.Column title="Ações" width={90} render={(_, r: Iface) => (
            <Popconfirm title={`Remover VLAN ${r.interface}?`} okText="Remover" okButtonProps={{ danger: true }}
              onConfirm={() => remove(r.interface)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )} />
        </Table>
      </Card>

      <Modal title={<Space><TagOutlined /> Nova VLAN</Space>} open={open} onCancel={() => setOpen(false)}
        onOk={submit} okText="Criar VLAN" confirmLoading={saving} width={520} destroyOnClose>
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Row gutter={16}>
            <Col xs={24} md={14}>
              <Form.Item name="parent" label="Interface pai" rules={[{ required: true, message: "Selecione a interface física" }]}
                tooltip="A placa física sobre a qual a VLAN trafega (porta tronco no switch).">
                <Select showSearch options={parentOptions} placeholder="ens19" optionFilterProp="label" />
              </Form.Item>
            </Col>
            <Col xs={24} md={10}>
              <Form.Item name="vlan_id" label="Número da VLAN (tag)"
                rules={[{ required: true, message: "Informe o número (1–4094)" }]}
                tooltip="Identificador 802.1Q. Deve coincidir com o configurado no switch.">
                <InputNumber min={1} max={4094} style={{ width: "100%" }} placeholder="10" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="name" label="Nome da VLAN (interface)"
            rules={[{ pattern: /^[a-z][a-z0-9_-]{1,14}$/, message: "minúsculas, ex.: vlan10, guest" }]}
            tooltip="Nome da sub-interface no sistema. Se vazio, será vlan<tag> (ex.: vlan10).">
            <Input placeholder="vlan10 (opcional)" className="mx-mono" />
          </Form.Item>
          <Form.Item name="description" label="Apelido / descrição">
            <Input placeholder="ex.: Convidados Wi-Fi" maxLength={64} />
          </Form.Item>

          <Divider plain>Endereçamento IPv4</Divider>
          <Form.Item name="ipv4_mode" label="Modo" initialValue="none">
            <Segmented options={[
              { label: "Sem IP", value: "none" },
              { label: "Estático", value: "static" },
              { label: "DHCP", value: "dhcp" },
            ]} onChange={(v) => setMode(v as any)} />
          </Form.Item>
          <Alert type="info" showIcon style={{ marginBottom: 12 }}
            message="Dica" banner
            description="Para usar a VLAN como uma rede com DHCP/DNS próprios, defina um IP estático aqui (ex.: 192.168.10.1/24) e depois crie a zona correspondente em Rede › Zonas apontando para esta VLAN." />
          {mode === "static" && (
            <>
              <Form.Item name="address" label="Endereço / CIDR do appliance"
                rules={[{ required: true, message: "Informe o IP/CIDR" },
                  { pattern: /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/, message: "ex.: 192.168.10.1/24" }]}>
                <Input placeholder="192.168.10.1/24" className="mx-mono" />
              </Form.Item>
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item name="nameservers" label="DNS (opcional)">
                    <Select mode="tags" tokenSeparators={[",", " "]} placeholder="1.1.1.1" className="mx-mono" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="mtu" label="MTU (opcional)" tooltip="Normalmente herda o pai (1500).">
                    <InputNumber min={576} max={9216} style={{ width: "100%" }} placeholder="1500" />
                  </Form.Item>
                </Col>
              </Row>
            </>
          )}
        </Form>
      </Modal>
    </div>
  );
};
