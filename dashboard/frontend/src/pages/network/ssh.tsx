import { useCallback, useEffect, useRef, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Button, Space, Typography, Alert,
  Form, Input, InputNumber, Switch, Segmented, Modal, Popconfirm,
  message as antdMessage,
} from "antd";
import {
  SafetyCertificateOutlined, ReloadOutlined, PlusOutlined, EditOutlined,
  CheckCircleFilled, CloseCircleFilled, LockOutlined, GlobalOutlined,
  ApiOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text, Paragraph } = Typography;

type Rule = {
  id?: string;
  source: string;
  description: string;
  enabled: boolean;
};

type SshAccess = {
  port: number;
  wan_policy: "throttle" | "allowlist" | "block";
  wan_rate: string;
  allow_rules: Rule[];
  live: { active: boolean; listen_ports: number[] };
};

const POLICY_LABEL: Record<string, string> = {
  throttle: "Limitado (anti-força-bruta)",
  allowlist: "Lista de permissões",
  block: "Bloqueado da WAN",
};

export function SshAccessPage() {
  const [data, setData] = useState<SshAccess | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [policy, setPolicy] = useState<"throttle" | "allowlist" | "block">("throttle");
  const [port, setPort] = useState(22);
  const [rate, setRate] = useState("15/minute");
  const [editing, setEditing] = useState<Rule | null>(null);
  const [form] = Form.useForm();
  const dirtyRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<SshAccess>("/api/network/ssh-access");
      setData(r.data);
      if (!dirtyRef.current) {
        setPolicy(r.data.wan_policy);
        setPort(r.data.port);
        setRate(r.data.wan_rate);
      }
    } catch {
      /* ignore */
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(() => load(true), 8000);
    return () => window.clearInterval(t);
  }, [load]);

  const markDirty = () => { dirtyRef.current = true; };

  const savePolicy = async () => {
    setSaving(true);
    try {
      const r = await api.put<SshAccess>("/api/network/ssh-access", {
        port, wan_policy: policy, wan_rate: rate,
      });
      setData(r.data);
      dirtyRef.current = false;
      antdMessage.success("Política de acesso SSH aplicada");
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao aplicar");
    } finally {
      setSaving(false);
    }
  };

  const openEditor = (rule: Rule | null) => {
    const d = rule ? { ...rule } : { source: "", description: "", enabled: true };
    setEditing(d);
    form.setFieldsValue(d);
  };

  const submitRule = async () => {
    const vals = await form.validateFields();
    try {
      if (editing?.id) {
        await api.put(`/api/network/ssh-access/rules/${editing.id}`, vals);
      } else {
        await api.post("/api/network/ssh-access/rules", vals);
      }
      antdMessage.success("Regra de liberação salva");
      setEditing(null);
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar regra");
    }
  };

  const removeRule = async (id?: string) => {
    if (!id) return;
    try {
      await api.delete(`/api/network/ssh-access/rules/${id}`);
      antdMessage.success("Regra removida");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao remover");
    }
  };

  const rules = data?.allow_rules || [];
  const activeRules = rules.filter((r) => r.enabled).length;
  const live = data?.live;
  const portMatches = !!live && (live.listen_ports.includes(port) || live.listen_ports.length === 0);

  const columns = [
    {
      title: "Estado",
      key: "state",
      width: 90,
      render: (_: any, r: Rule) =>
        r.enabled
          ? <Tag icon={<CheckCircleFilled />} color="success">ativa</Tag>
          : <Tag icon={<CloseCircleFilled />} color="default">inativa</Tag>,
    },
    {
      title: "Origem liberada",
      dataIndex: "source",
      render: (v: string, r: Rule) => (
        <Space direction="vertical" size={0}>
          <Text code>{v}</Text>
          {r.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>{r.description}</Text>
          )}
        </Space>
      ),
    },
    {
      title: "",
      key: "actions",
      width: 140,
      render: (_: any, r: Rule) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(r)} />
          <Popconfirm title="Remover esta liberação?" onConfirm={() => removeRule(r.id)}>
            <Button size="small" danger>Remover</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Rede"
        title="Acesso remoto SSH"
        subtitle="Controle quem alcança o SSH do appliance pela internet e crie regras de liberação no firewall"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
              Atualizar
            </Button>
            <Button type="primary" onClick={savePolicy} loading={saving}>
              Aplicar política
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Anti-bloqueio garantido"
        description="A LAN e as zonas internas sempre alcançam o SSH, e sessões já conectadas nunca são derrubadas por uma mudança de política. Estas regras controlam apenas o acesso vindo da WAN (internet)."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<GlobalOutlined />} color="#6366f1" label="Política WAN"
            value={POLICY_LABEL[data?.wan_policy || "throttle"]} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<SafetyCertificateOutlined />} color="#22c55e"
            label="Origens liberadas" value={activeRules} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<ApiOutlined />} color={live?.active ? "#22c55e" : "#ef4444"}
            label="Serviço SSH" value={live?.active ? "ativo" : "parado"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<LockOutlined />} color="#0ea5e9" label="Porta (firewall)"
            value={port} />
        </Col>
      </Row>

      <Card style={{ marginBottom: 16 }} title={<Space><GlobalOutlined />Política de acesso pela WAN</Space>}>
        <Segmented
          block
          value={policy}
          onChange={(v) => { setPolicy(v as any); markDirty(); }}
          options={[
            { value: "throttle", label: "Limitado (anti-força-bruta)" },
            { value: "allowlist", label: "Somente lista de permissões" },
            { value: "block", label: "Bloquear da WAN" },
          ]}
        />
        <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 16 }}>
          {policy === "throttle" &&
            "Aceita SSH de qualquer origem na WAN, mas limita novas conexões por IP de origem para frear ataques de força bruta."}
          {policy === "allowlist" &&
            "Aceita SSH na WAN apenas das origens liberadas abaixo. Todas as demais tentativas vindas da internet são descartadas. Cadastre ao menos uma origem antes de aplicar."}
          {policy === "block" &&
            "Nenhuma nova conexão SSH é aceita pela WAN. O acesso continua disponível pela LAN/zonas internas e pela VPN."}
        </Paragraph>

        <Row gutter={[24, 16]} align="middle">
          <Col xs={12} md={6}>
            <Text type="secondary">Porta SSH (firewall)</Text>
            <InputNumber style={{ width: "100%" }} min={1} max={65535} value={port}
              onChange={(v) => { setPort(Number(v)); markDirty(); }} />
          </Col>
          {policy === "throttle" && (
            <Col xs={12} md={6}>
              <Text type="secondary">Limite por origem</Text>
              <Input value={rate} placeholder="15/minute"
                onChange={(e) => { setRate(e.target.value); markDirty(); }} />
            </Col>
          )}
          <Col xs={24} md={12}>
            {live && !portMatches && (
              <Alert type="warning" showIcon
                message={`O serviço SSH está escutando em ${live.listen_ports.join(", ") || "—"}, diferente da porta liberada (${port}). Ajuste a porta para evitar perder o acesso remoto.`} />
            )}
          </Col>
        </Row>
      </Card>

      <Card
        title={<Space><SafetyCertificateOutlined />Regras de liberação (origens permitidas)</Space>}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>
            Nova liberação
          </Button>
        }
      >
        {policy !== "allowlist" && (
          <Alert style={{ marginBottom: 12 }} type="info" showIcon
            message="Estas liberações entram em vigor quando a política está em ‘Somente lista de permissões’. Você pode cadastrá-las desde já." />
        )}
        <Table rowKey="id" size="small" loading={loading} dataSource={rules}
          columns={columns as any} pagination={false}
          locale={{ emptyText: "Nenhuma origem liberada" }} />
      </Card>

      {editing && (
        <Modal
          open
          title={editing?.id ? "Editar liberação" : "Nova liberação SSH"}
          onCancel={() => setEditing(null)}
          onOk={submitRule}
          okText="Salvar"
          destroyOnClose
        >
          <Form form={form} layout="vertical" preserve={false}>
            <Form.Item name="source" label="Origem (IP ou CIDR)"
              rules={[{ required: true, message: "informe um IP ou rede (CIDR)" }]}>
              <Input placeholder="203.0.113.10 ou 192.168.0.0/24" />
            </Form.Item>
            <Form.Item name="description" label="Descrição">
              <Input placeholder="ex: matriz, suporte, admin remoto" />
            </Form.Item>
            <Form.Item name="enabled" label="Ativa" valuePropName="checked" initialValue={true}>
              <Switch />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  );
}
