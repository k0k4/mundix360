import { useCallback, useEffect, useRef, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Select, Button, Space, Typography, Alert,
  Tooltip, Form, Input, InputNumber, Switch, Segmented, Divider, Modal,
  Popconfirm, message as antdMessage,
} from "antd";
import {
  DeploymentUnitOutlined, ReloadOutlined, PlusOutlined, EditOutlined,
  ThunderboltOutlined, GlobalOutlined, CheckCircleFilled, CloseCircleFilled,
  ClockCircleOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";
import { useInterfaces } from "../../hooks/useInterfaces";

const { Text } = Typography;

type Gateway = {
  id?: string;
  name: string;
  iface: string;
  gateway: string;
  monitor_ip: string;
  weight: number;
  tier: number;
  enabled: boolean;
  effective_gateway?: string | null;
  src_ip?: string | null;
  up?: boolean | null;
  latency_ms?: number | null;
};

type Status = {
  enabled: boolean;
  mode: "failover" | "loadbalance";
  interval: number;
  down_after: number;
  up_after: number;
  monitor_running: boolean;
  active_gateways: string[];
  gateways: Gateway[];
};

const blankGw: Gateway = {
  name: "",
  iface: "",
  gateway: "auto",
  monitor_ip: "8.8.8.8",
  weight: 1,
  tier: 1,
  enabled: true,
};

export function MultiWanPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [mode, setMode] = useState<"failover" | "loadbalance">("failover");
  const [interval, setIntervalS] = useState(10);
  const [downAfter, setDownAfter] = useState(3);
  const [upAfter, setUpAfter] = useState(2);
  const [gateways, setGateways] = useState<Gateway[]>([]);
  const [editing, setEditing] = useState<{ gw: Gateway; idx: number } | null>(null);
  const [form] = Form.useForm();
  const { options: ifaceOptions } = useInterfaces();
  const dirtyRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<Status>("/api/network/multiwan/status");
      setStatus(r.data);
      // Don't clobber unsaved edits during background polling.
      if (!dirtyRef.current) {
        setEnabled(r.data.enabled);
        setMode(r.data.mode);
        setIntervalS(r.data.interval);
        setDownAfter(r.data.down_after);
        setUpAfter(r.data.up_after);
        setGateways(r.data.gateways.map((g) => ({ ...g })));
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

  const markDirty = () => {
    dirtyRef.current = true;
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/api/network/multiwan/config", {
        enabled,
        mode,
        interval,
        down_after: downAfter,
        up_after: upAfter,
        gateways: gateways.map((g) => ({
          id: g.id,
          name: g.name,
          iface: g.iface,
          gateway: g.gateway || "auto",
          monitor_ip: g.monitor_ip,
          weight: g.weight,
          tier: g.tier,
          enabled: g.enabled,
        })),
      });
      dirtyRef.current = false;
      antdMessage.success("Multi-WAN aplicado");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao aplicar");
    } finally {
      setSaving(false);
    }
  };

  const openEditor = (gw: Gateway | null, idx: number) => {
    const data = gw ? { ...gw } : { ...blankGw };
    setEditing({ gw: data, idx });
    form.setFieldsValue(data);
  };

  const submitGw = async () => {
    const vals = await form.validateFields();
    if (!editing) return;
    const next = [...gateways];
    const gw: Gateway = { ...(editing.gw || {}), ...vals };
    if (editing.idx < 0) next.push(gw);
    else next[editing.idx] = gw;
    setGateways(next);
    markDirty();
    setEditing(null);
  };

  const removeGw = (idx: number) => {
    setGateways(gateways.filter((_, i) => i !== idx));
    markDirty();
  };

  const total = gateways.length;
  const up = (status?.gateways || []).filter((g) => g.up).length;
  const down = (status?.gateways || []).filter((g) => g.up === false).length;

  const columns = [
    {
      title: "Estado",
      key: "state",
      width: 90,
      render: (_: any, g: Gateway) => {
        if (!enabled) return <Tag>—</Tag>;
        if (g.up === true)
          return <Tag icon={<CheckCircleFilled />} color="success">UP</Tag>;
        if (g.up === false)
          return <Tag icon={<CloseCircleFilled />} color="error">DOWN</Tag>;
        return <Tag icon={<ClockCircleOutlined />} color="default">?</Tag>;
      },
    },
    {
      title: "Nome",
      dataIndex: "name",
      render: (v: string, g: Gateway) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            tier {g.tier} · peso {g.weight}
          </Text>
        </Space>
      ),
    },
    {
      title: "Interface",
      dataIndex: "iface",
      render: (v: string, g: Gateway) => (
        <Space direction="vertical" size={0}>
          <Text code>{v}</Text>
          {g.src_ip && (
            <Text type="secondary" style={{ fontSize: 12 }}>src {g.src_ip}</Text>
          )}
        </Space>
      ),
    },
    {
      title: "Gateway",
      dataIndex: "gateway",
      render: (v: string, g: Gateway) => (
        <Space direction="vertical" size={0}>
          <Text>{v === "auto" ? "auto" : v}</Text>
          {g.effective_gateway && v === "auto" && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              → {g.effective_gateway}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: "Monitor",
      dataIndex: "monitor_ip",
      render: (v: string, g: Gateway) => (
        <Space direction="vertical" size={0}>
          <Text>{v}</Text>
          {g.latency_ms != null && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {g.latency_ms} ms
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: "Ativo",
      dataIndex: "enabled",
      width: 80,
      render: (v: boolean) => (v ? <Tag color="blue">sim</Tag> : <Tag>não</Tag>),
    },
    {
      title: "",
      key: "actions",
      width: 110,
      render: (_: any, g: Gateway, idx: number) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(g, idx)} />
          <Popconfirm title="Remover gateway?" onConfirm={() => removeGw(idx)}>
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
        title="Multi-WAN"
        subtitle="Failover e balanceamento de carga entre múltiplos links de internet"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
              Atualizar
            </Button>
            <Button type="primary" onClick={save} loading={saving}>
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
        description="Multi-WAN é desligado por padrão. Quando ativo, monitora cada link por ping e ajusta as rotas automaticamente. No modo failover usa o link de maior prioridade que estiver UP; no balanceamento distribui por peso (ECMP). Ideal para clientes com 2 ou 3 internets."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<DeploymentUnitOutlined />} color="#6366f1" label="Gateways" value={total} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CheckCircleFilled />} color="#22c55e" label="UP" value={enabled ? up : "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CloseCircleFilled />} color="#ef4444" label="DOWN" value={enabled ? down : "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard
            icon={<ThunderboltOutlined />}
            color="#f59e0b"
            label="Monitor"
            value={status?.monitor_running ? "ativo" : "parado"}
          />
        </Col>
      </Row>

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} md={8}>
            <Space>
              <Switch
                checked={enabled}
                onChange={(v) => { setEnabled(v); markDirty(); }}
              />
              <Text strong>{enabled ? "Multi-WAN ATIVO" : "Multi-WAN desligado"}</Text>
            </Space>
          </Col>
          <Col xs={24} md={8}>
            <Space direction="vertical" size={4} style={{ width: "100%" }}>
              <Text type="secondary" style={{ fontSize: 12 }}>Modo</Text>
              <Segmented
                value={mode}
                onChange={(v) => { setMode(v as any); markDirty(); }}
                options={[
                  { label: "Failover", value: "failover" },
                  { label: "Balanceamento", value: "loadbalance" },
                ]}
              />
            </Space>
          </Col>
          <Col xs={24} md={8}>
            {enabled && status?.active_gateways?.length ? (
              <Space direction="vertical" size={4}>
                <Text type="secondary" style={{ fontSize: 12 }}>Ativos agora</Text>
                <Space wrap>
                  {status.active_gateways.map((n) => (
                    <Tag key={n} color="green" icon={<GlobalOutlined />}>{n}</Tag>
                  ))}
                </Space>
              </Space>
            ) : null}
          </Col>
        </Row>
        <Divider style={{ margin: "16px 0" }} />
        <Row gutter={[24, 16]}>
          <Col xs={12} md={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>Intervalo de checagem (s)</Text>
            <InputNumber
              min={3} max={120} value={interval} style={{ width: "100%" }}
              onChange={(v) => { setIntervalS(v || 10); markDirty(); }}
            />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>Falhas p/ marcar DOWN</Text>
            <InputNumber
              min={1} max={10} value={downAfter} style={{ width: "100%" }}
              onChange={(v) => { setDownAfter(v || 3); markDirty(); }}
            />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>Sucessos p/ marcar UP</Text>
            <InputNumber
              min={1} max={10} value={upAfter} style={{ width: "100%" }}
              onChange={(v) => { setUpAfter(v || 2); markDirty(); }}
            />
          </Col>
        </Row>
      </Card>

      <Card
        title="Gateways (links WAN)"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null, -1)}>
            Adicionar gateway
          </Button>
        }
      >
        <Table
          rowKey={(g) => g.id || g.iface || g.name}
          dataSource={enabled || dirtyRef.current ? gateways : (status?.gateways || gateways)}
          columns={columns as any}
          pagination={false}
          loading={loading}
          locale={{ emptyText: "Nenhum gateway. Adicione ao menos um link WAN." }}
        />
      </Card>

      <Modal
        title={editing && editing.idx >= 0 ? "Editar gateway" : "Adicionar gateway"}
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={submitGw}
        okText="Salvar"
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={blankGw}>
          <Form.Item name="name" label="Nome" rules={[{ required: true, message: "Informe um nome" }]}>
            <Input placeholder="Ex.: WAN Vivo Fibra" />
          </Form.Item>
          <Form.Item name="iface" label="Interface" rules={[{ required: true, message: "Selecione a interface" }]}>
            <Select showSearch options={ifaceOptions} placeholder="Interface física da WAN" />
          </Form.Item>
          <Form.Item
            name="gateway"
            label="Gateway"
            tooltip="'auto' detecta o gateway a partir das rotas. Ou informe um IP."
          >
            <Input placeholder="auto" />
          </Form.Item>
          <Form.Item
            name="monitor_ip"
            label="IP de monitoramento"
            tooltip="IP pingado por este link para aferir saúde (ex.: 8.8.8.8, 1.1.1.1)."
            rules={[{ required: true, message: "Informe o IP de monitoramento" }]}
          >
            <Input placeholder="8.8.8.8" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="tier" label="Tier (prioridade)" tooltip="Menor = maior prioridade. Failover usa o menor tier UP.">
                <InputNumber min={1} max={10} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="weight" label="Peso" tooltip="No balanceamento, links de maior peso recebem mais tráfego.">
                <InputNumber min={1} max={256} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="enabled" label="Ativo" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
