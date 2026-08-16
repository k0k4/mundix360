import { useCallback, useEffect, useRef, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Button, Space, Typography, Alert, Tooltip,
  Form, Input, InputNumber, Switch, Modal, Popconfirm, message as antdMessage,
} from "antd";
import {
  ApiOutlined, ReloadOutlined, PlusOutlined, EditOutlined, EyeOutlined,
  PoweroffOutlined, ThunderboltOutlined, GlobalOutlined, CheckCircleFilled,
  CloseCircleFilled, WifiOutlined, KeyOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";
import { useInterfaces } from "../../hooks/useInterfaces";

const { Text, Paragraph } = Typography;

type Link = {
  id: string;
  name: string;
  nic: string;
  username: string;
  unit: number;
  iface: string;
  enabled: boolean;
  default_route: boolean;
  route_metric: number;
  use_peer_dns: boolean;
  mtu: number;
  service_active: boolean;
  autostart: boolean;
  up: boolean;
  local_ip: string | null;
  remote_ip: string | null;
  is_default: boolean;
};

type FormState = {
  id?: string;
  name: string;
  nic: string;
  username: string;
  password: string;
  enabled: boolean;
  default_route: boolean;
  route_metric: number;
  use_peer_dns: boolean;
  mtu: number;
};

const EMPTY: FormState = {
  name: "",
  nic: "",
  username: "",
  password: "",
  enabled: true,
  default_route: true,
  route_metric: 0,
  use_peer_dns: false,
  mtu: 1492,
};

export function PppoePage() {
  const [links, setLinks] = useState<Link[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [logLink, setLogLink] = useState<Link | null>(null);
  const [logData, setLogData] = useState<{ unit: string; lines: string[] } | null>(null);
  const [logLoading, setLogLoading] = useState(false);
  const logBodyRef = useRef<HTMLDivElement>(null);
  const { options: ifaceOptions } = useInterfaces();

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<{ links: Link[] }>("/api/network/pppoe");
      setLinks(r.data.links || []);
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

  // Live log viewer: poll the link's systemd journal every 2s while open.
  useEffect(() => {
    if (!logLink) {
      setLogData(null);
      return;
    }
    let active = true;
    const fetchLogs = async () => {
      try {
        const r = await api.get<{ unit: string; lines: string[] }>(
          `/api/network/pppoe/${logLink.id}/logs`,
          { params: { lines: 400 } },
        );
        if (active) setLogData(r.data);
      } catch {
        /* ignore */
      }
    };
    setLogLoading(true);
    fetchLogs().finally(() => {
      if (active) setLogLoading(false);
    });
    const t = window.setInterval(fetchLogs, 2000);
    return () => {
      active = false;
      window.clearInterval(t);
    };
  }, [logLink]);

  useEffect(() => {
    const el = logBodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logData]);

  const logLineColor = (l: string) => {
    const u = l.toUpperCase();
    if (/\b(ERROR|FATAL|CANNOT|FAILED|FAILURE|AUTH|UNAUTHORIZED|TIMEOUT|REJECT)\b/.test(u))
      return "#ff7875";
    if (/\b(WARN|WARNING|RECONNECT|RETRY|TERMINAT|HANGUP|DISCONNECT)\b/.test(u))
      return "#ffc53d";
    if (/\b(LOCAL IP ADDRESS|REMOTE IP ADDRESS|CONNECT|PAP AUTHENTICATION SUCCEEDED|CHAP AUTHENTICATION SUCCEEDED)\b/.test(u))
      return "#95de64";
    return "#d9d9d9";
  };

  const openNew = () => {
    setForm(EMPTY);
    setModalOpen(true);
  };

  const openEdit = (l: Link) => {
    setForm({
      id: l.id,
      name: l.name,
      nic: l.nic,
      username: l.username,
      password: "",
      enabled: l.enabled,
      default_route: l.default_route,
      route_metric: l.route_metric,
      use_peer_dns: l.use_peer_dns,
      mtu: l.mtu,
    });
    setModalOpen(true);
  };

  const patch = (p: Partial<FormState>) => setForm((f) => ({ ...f, ...p }));

  const save = async () => {
    if (!form.name || !form.nic || !form.username) {
      antdMessage.error("Informe nome, interface e usuário");
      return;
    }
    if (!form.id && !form.password) {
      antdMessage.error("Informe a senha do PPPoE");
      return;
    }
    setSaving(true);
    try {
      const body: any = { ...form };
      // On edit, an empty password means "keep the current one".
      if (form.id && !form.password) delete body.password;
      if (form.id) await api.put(`/api/network/pppoe/${form.id}`, body);
      else await api.post("/api/network/pppoe", body);
      antdMessage.success(form.id ? "Link atualizado" : "Link PPPoE criado");
      setModalOpen(false);
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const act = async (l: Link, verb: "connect" | "disconnect") => {
    setBusyId(l.id);
    try {
      await api.post(`/api/network/pppoe/${l.id}/${verb}`);
      antdMessage.success(verb === "connect" ? "Discando…" : "Link desconectado");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha na operação");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (l: Link) => {
    setBusyId(l.id);
    try {
      await api.delete(`/api/network/pppoe/${l.id}`);
      antdMessage.success("Link removido");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao remover");
    } finally {
      setBusyId(null);
    }
  };

  const toggleAutostart = async (l: Link, v: boolean) => {
    setBusyId(l.id);
    try {
      await api.put(`/api/network/pppoe/${l.id}/enabled`, { enabled: v });
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha");
    } finally {
      setBusyId(null);
    }
  };

  const total = links.length;
  const upCount = links.filter((l) => l.up).length;
  const activeWan = links.find((l) => l.is_default);

  const columns = [
    {
      title: "Estado",
      key: "state",
      width: 96,
      render: (_: any, l: Link) =>
        l.up ? (
          <Tag icon={<CheckCircleFilled />} color="success">CONECTADO</Tag>
        ) : l.service_active ? (
          <Tag icon={<ThunderboltOutlined />} color="processing">DISCANDO</Tag>
        ) : (
          <Tag icon={<CloseCircleFilled />} color="default">PARADO</Tag>
        ),
    },
    {
      title: "Link",
      dataIndex: "name",
      render: (v: string, l: Link) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            <Text strong>{v}</Text>
            {l.is_default && (
              <Tag color="gold" icon={<GlobalOutlined />} style={{ marginInlineEnd: 0 }}>
                WAN
              </Tag>
            )}
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <KeyOutlined /> {l.username}
          </Text>
        </Space>
      ),
    },
    {
      title: "Interface",
      key: "iface",
      render: (_: any, l: Link) => (
        <Space direction="vertical" size={0}>
          <Text code>{l.iface}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <WifiOutlined /> {l.nic}
          </Text>
        </Space>
      ),
    },
    {
      title: "Endereços",
      key: "addr",
      render: (_: any, l: Link) =>
        l.up ? (
          <Space direction="vertical" size={0}>
            <Text>{l.local_ip}</Text>
            {l.remote_ip && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                gw {l.remote_ip}
              </Text>
            )}
          </Space>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: "Auto",
      dataIndex: "autostart",
      width: 70,
      render: (_: any, l: Link) => (
        <Switch
          size="small"
          checked={l.autostart}
          loading={busyId === l.id}
          onChange={(v) => toggleAutostart(l, v)}
        />
      ),
    },
    {
      title: "",
      key: "actions",
      width: 200,
      render: (_: any, l: Link) => (
        <Space size={4}>
          {l.up || l.service_active ? (
            <Tooltip title="Desconectar">
              <Button
                size="small"
                danger
                icon={<PoweroffOutlined />}
                loading={busyId === l.id}
                onClick={() => act(l, "disconnect")}
              />
            </Tooltip>
          ) : (
            <Tooltip title="Conectar / discar">
              <Button
                size="small"
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={busyId === l.id}
                onClick={() => act(l, "connect")}
              />
            </Tooltip>
          )}
          <Tooltip title="Ver log ao vivo">
            <Button size="small" icon={<EyeOutlined />} onClick={() => setLogLink(l)} />
          </Tooltip>
          <Tooltip title="Editar">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(l)} />
          </Tooltip>
          <Popconfirm title="Remover este link PPPoE?" onConfirm={() => remove(l)}>
            <Button size="small" danger>
              Remover
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Rede"
        title="PPPoE"
        subtitle="Autenticação de links de internet entregues via PPPoE (fibra/GPON, rádio/WISP)"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
              Atualizar
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>
              Novo link PPPoE
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Como funciona"
        description="Cada link disca (autentica) na operadora pela placa de rede escolhida e recebe o IP público numa interface pppN. O link marcado como 'rota padrão' passa a ser a WAN do firewall (NAT e regras acompanham automaticamente). Você pode cadastrar quantos links forem necessários — para failover automático entre eles, combine com a tela Multi-WAN."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<ApiOutlined />} color="#6366f1" label="Links" value={total} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CheckCircleFilled />} color="#22c55e" label="Conectados" value={upCount} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard
            icon={<CloseCircleFilled />}
            color="#ef4444"
            label="Offline"
            value={total - upCount}
          />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard
            icon={<GlobalOutlined />}
            color="#f59e0b"
            label="WAN ativa"
            value={activeWan ? activeWan.iface : "—"}
          />
        </Col>
      </Row>

      <Card>
        <Table
          rowKey="id"
          dataSource={links}
          columns={columns as any}
          pagination={false}
          loading={loading}
          locale={{ emptyText: "Nenhum link PPPoE. Clique em 'Novo link PPPoE' para começar." }}
        />
      </Card>

      <Modal
        title={form.id ? "Editar link PPPoE" : "Novo link PPPoE"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={save}
        okText={form.id ? "Salvar" : "Criar"}
        confirmLoading={saving}
        width={620}
        destroyOnClose
      >
        <Form layout="vertical">
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item label="Nome do link" required>
                <Input
                  value={form.name}
                  onChange={(e) => patch({ name: e.target.value })}
                  placeholder="Ex.: LinQ - Principal"
                />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item
                label="Interface de rede (placa onde está o modem/ONT)"
                required
                tooltip="A placa física conectada ao equipamento da operadora. Ela não deve ter IP próprio; o IP público virá pelo PPPoE."
              >
                <Input.Group compact>
                  <Form.Item noStyle>
                    <Input
                      style={{ width: "100%" }}
                      value={form.nic}
                      onChange={(e) => patch({ nic: e.target.value })}
                      placeholder="Ex.: enp1s0"
                      list="pppoe-nics"
                    />
                  </Form.Item>
                </Input.Group>
                <datalist id="pppoe-nics">
                  {ifaceOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </datalist>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="Usuário (login)" required>
                <Input
                  value={form.username}
                  onChange={(e) => patch({ username: e.target.value })}
                  placeholder="versalagro"
                  autoComplete="off"
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="Senha"
                required={!form.id}
                tooltip={form.id ? "Deixe em branco para manter a senha atual." : undefined}
              >
                <Input.Password
                  value={form.password}
                  onChange={(e) => patch({ password: e.target.value })}
                  placeholder={form.id ? "•••••• (inalterada)" : "Senha do PPPoE"}
                  autoComplete="new-password"
                />
              </Form.Item>
            </Col>
          </Row>

          <Card size="small" title="Opções" style={{ marginTop: 4 }}>
            <Row gutter={16}>
              <Col span={24}>
                <Space>
                  <Switch
                    checked={form.default_route}
                    onChange={(v) => patch({ default_route: v })}
                  />
                  <Text>Usar como rota padrão (WAN) do firewall</Text>
                </Space>
                <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 4, marginBottom: 12 }}>
                  Quando ativo, este link instala a rota padrão e passa a ser a WAN.
                  Com vários links como rota padrão, o de menor métrica é o preferido
                  e o failover é automático na queda.
                </Paragraph>
              </Col>
              <Col span={12}>
                <Form.Item
                  label="Métrica da rota"
                  tooltip="Menor = maior prioridade. 0 = automático (por ordem do link)."
                  style={{ marginBottom: 8 }}
                >
                  <InputNumber
                    min={0}
                    max={4096}
                    value={form.route_metric}
                    onChange={(v) => patch({ route_metric: v ?? 0 })}
                    style={{ width: "100%" }}
                    disabled={!form.default_route}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  label="MTU"
                  tooltip="PPPoE adiciona 8 bytes de cabeçalho; 1492 é o padrão."
                  style={{ marginBottom: 8 }}
                >
                  <InputNumber
                    min={1280}
                    max={1500}
                    value={form.mtu}
                    onChange={(v) => patch({ mtu: v ?? 1492 })}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Space>
                  <Switch
                    checked={form.use_peer_dns}
                    onChange={(v) => patch({ use_peer_dns: v })}
                  />
                  <Text type="secondary">Usar DNS da operadora</Text>
                </Space>
              </Col>
              <Col span={12}>
                <Space>
                  <Switch checked={form.enabled} onChange={(v) => patch({ enabled: v })} />
                  <Text type="secondary">Conectar no boot (autostart)</Text>
                </Space>
              </Col>
            </Row>
          </Card>
        </Form>
      </Modal>

      <Modal
        open={!!logLink}
        title={
          <Space>
            <EyeOutlined />
            <span>Log ao vivo — {logLink?.name}</span>
            <Tag color="green" style={{ marginLeft: 4 }}>
              <span className="mx-pulse" /> ao vivo (2s)
            </Tag>
          </Space>
        }
        onCancel={() => setLogLink(null)}
        width={860}
        footer={[
          <Text key="unit" type="secondary" className="mx-mono" style={{ float: "left", fontSize: 11 }}>
            {logData?.unit || ""}
          </Text>,
          <Button key="close" onClick={() => setLogLink(null)}>
            Fechar
          </Button>,
        ]}
        destroyOnClose
      >
        <div
          ref={logBodyRef}
          style={{
            background: "#0b0e14",
            borderRadius: 8,
            padding: "12px 14px",
            height: 480,
            overflow: "auto",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: 12,
            lineHeight: 1.55,
          }}
        >
          {logData?.lines?.length ? (
            logData.lines.map((l, i) => (
              <div
                key={i}
                style={{ color: logLineColor(l), whiteSpace: "pre-wrap", wordBreak: "break-word" }}
              >
                {l}
              </div>
            ))
          ) : (
            <Text style={{ color: "#8c8c8c" }}>
              {logLoading
                ? "Carregando…"
                : "Sem entradas de log. O link pode nunca ter sido discado — conecte-o e o log aparecerá aqui em tempo real."}
            </Text>
          )}
        </div>
      </Modal>
    </div>
  );
}
