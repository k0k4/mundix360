import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Row,
  Col,
  Button,
  Space,
  Typography,
  Alert,
  Input,
  Switch,
  Table,
  Tag,
  Modal,
  Form,
  Upload,
  Tooltip,
  Popconfirm,
  message as antdMessage,
} from "antd";
import {
  SafetyCertificateOutlined,
  ReloadOutlined,
  PlusOutlined,
  UploadOutlined,
  ApiOutlined,
  CheckCircleFilled,
  DeleteOutlined,
  EditOutlined,
  CloudUploadOutlined,
  GlobalOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text, Paragraph } = Typography;

type ClientStatus = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  dev: string;
  route_lan: boolean;
  accept_pushed_routes: boolean;
  remote_subnets: string[];
  block_subnets: string[];
  remote_host: string;
  remote_port: number | null;
  remote_proto: string;
  username: string;
  has_password: boolean;
  requires_auth: boolean;
  unit_active: boolean;
  tunnel_up: boolean;
  tunnel_address: string;
};

type FormState = {
  id?: string;
  name: string;
  description: string;
  enabled: boolean;
  config: string;
  username: string;
  password: string;
  route_lan: boolean;
  accept_pushed_routes: boolean;
  remote_subnets: string;
  block_subnets: string;
  configTouched: boolean;
  has_password: boolean;
};

const EMPTY: FormState = {
  name: "",
  description: "",
  enabled: true,
  config: "",
  username: "",
  password: "",
  route_lan: false,
  accept_pushed_routes: true,
  remote_subnets: "",
  block_subnets: "",
  configTouched: true,
  has_password: false,
};

const tunnelState = (c: ClientStatus) =>
  !c.enabled
    ? { tag: "desligado", color: "default" as const }
    : c.tunnel_up
      ? { tag: "conectado", color: "success" as const }
      : c.unit_active
        ? { tag: "conectando…", color: "warning" as const }
        : { tag: "parado", color: "error" as const };

export function OvpnClientPage() {
  const [clients, setClients] = useState<ClientStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<{ ovpn_clients: ClientStatus[] }>("/api/vpn/status");
      setClients(r.data.ovpn_clients || []);
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

  const openNew = () => {
    setForm(EMPTY);
    setModalOpen(true);
  };

  const openEdit = (c: ClientStatus) => {
    setForm({
      id: c.id,
      name: c.name,
      description: c.description,
      enabled: c.enabled,
      config: "",
      username: c.username,
      password: "",
      route_lan: c.route_lan,
      accept_pushed_routes: c.accept_pushed_routes,
      remote_subnets: (c.remote_subnets || []).join(", "),
      block_subnets: (c.block_subnets || []).join(", "),
      configTouched: false,
      has_password: c.has_password,
    });
    setModalOpen(true);
  };

  const patch = (p: Partial<FormState>) => setForm((f) => ({ ...f, ...p }));

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      patch({ config: String(reader.result || ""), configTouched: true });
      antdMessage.success(`Perfil "${file.name}" carregado`);
    };
    reader.readAsText(file);
    return false;
  };

  const splitList = (s: string) =>
    s.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);

  const save = async () => {
    if (!form.name.trim()) {
      antdMessage.warning("Informe um nome para a conexão");
      return;
    }
    if (form.configTouched && !form.config.trim() && !form.id) {
      antdMessage.warning("Importe ou cole o conteúdo do arquivo .ovpn");
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        id: form.id,
        name: form.name,
        description: form.description,
        enabled: form.enabled,
        username: form.username,
        route_lan: form.route_lan,
        accept_pushed_routes: form.accept_pushed_routes,
        remote_subnets: splitList(form.remote_subnets),
        block_subnets: splitList(form.block_subnets),
      };
      if (form.configTouched && form.config.trim()) body.config = form.config;
      if (form.password) body.password = form.password;
      const r = await api.post<ClientStatus & { applied: boolean; detail: string }>(
        "/api/vpn/ovpn-clients",
        body,
      );
      if (r.data.enabled && !r.data.applied) {
        antdMessage.warning(
          `Salvo, mas o túnel não subiu: ${r.data.detail || "verifique o perfil/credenciais"}`,
        );
      } else {
        antdMessage.success("Conexão salva");
      }
      setModalOpen(false);
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.delete(`/api/vpn/ovpn-clients/${id}`);
      antdMessage.success("Conexão removida");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao remover");
    }
  };

  const toggle = async (c: ClientStatus, enabled: boolean) => {
    try {
      await api.post("/api/vpn/ovpn-clients", {
        id: c.id,
        name: c.name,
        description: c.description,
        enabled,
        username: c.username,
        route_lan: c.route_lan,
        accept_pushed_routes: c.accept_pushed_routes,
        remote_subnets: c.remote_subnets,
        block_subnets: c.block_subnets,
      });
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao alterar");
    }
  };

  const connected = clients.filter((c) => c.tunnel_up).length;
  const routed = clients.filter((c) => c.route_lan && c.enabled).length;

  return (
    <div>
      <PageHeader
        eyebrow="VPN"
        title="OpenVPN (cliente / dial-out)"
        subtitle="Importe um arquivo .ovpn e disque para um servidor OpenVPN remoto (matriz/nuvem)"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
              Atualizar
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>
              Importar .ovpn
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Aqui o Mundix é o CLIENTE OpenVPN"
        description="Importe o perfil .ovpn fornecido pelo servidor remoto. As credenciais (quando exigidas) ficam protegidas no appliance (0600). Você decide se a LAN local é roteada (NAT) pelo túnel e quais sub-redes remotas ficam acessíveis ou bloqueadas — as regras de firewall são geradas e mantidas automaticamente."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={8}>
          <KpiCard icon={<CloudUploadOutlined />} color="#6366f1" label="Conexões" value={clients.length} />
        </Col>
        <Col xs={8}>
          <KpiCard icon={<CheckCircleFilled />} color="#22c55e" label="Conectadas" value={connected} />
        </Col>
        <Col xs={8}>
          <KpiCard icon={<GlobalOutlined />} color="#0ea5e9" label="Roteando a LAN" value={routed} />
        </Col>
      </Row>

      <Card>
        <Table
          loading={loading}
          dataSource={clients}
          rowKey="id"
          size="small"
          pagination={false}
          locale={{ emptyText: "Nenhuma conexão importada ainda" }}
          columns={[
            {
              title: "Conexão",
              dataIndex: "name",
              render: (v, c: ClientStatus) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{v}</Text>
                  {c.description ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {c.description}
                    </Text>
                  ) : null}
                </Space>
              ),
            },
            {
              title: "Servidor remoto",
              render: (_: any, c: ClientStatus) => (
                <Text className="mx-mono" style={{ fontSize: 12 }}>
                  {c.remote_host
                    ? `${c.remote_host}:${c.remote_port ?? "?"}${c.remote_proto ? "/" + c.remote_proto : ""}`
                    : "—"}
                </Text>
              ),
            },
            {
              title: "Estado",
              width: 130,
              render: (_: any, c: ClientStatus) => {
                const st = tunnelState(c);
                return (
                  <Space direction="vertical" size={0}>
                    <Tag color={st.color}>{st.tag}</Tag>
                    {c.tunnel_address ? (
                      <Text type="secondary" className="mx-mono" style={{ fontSize: 11 }}>
                        {c.tunnel_address}
                      </Text>
                    ) : null}
                  </Space>
                );
              },
            },
            {
              title: "Rede",
              render: (_: any, c: ClientStatus) => (
                <Space size={4} wrap>
                  {c.route_lan ? (
                    <Tag color="blue">LAN roteada</Tag>
                  ) : (
                    <Tag>só o appliance</Tag>
                  )}
                  {c.block_subnets?.length ? (
                    <Tag color="red">{c.block_subnets.length} bloqueio(s)</Tag>
                  ) : null}
                  <Text type="secondary" className="mx-mono" style={{ fontSize: 11 }}>
                    {c.dev}
                  </Text>
                </Space>
              ),
            },
            {
              title: "Ativo",
              width: 70,
              render: (_: any, c: ClientStatus) => (
                <Switch
                  size="small"
                  checked={c.enabled}
                  onChange={(v) => toggle(c, v)}
                />
              ),
            },
            {
              title: "",
              width: 90,
              render: (_: any, c: ClientStatus) => (
                <Space>
                  <Tooltip title="Editar">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(c)} />
                  </Tooltip>
                  <Popconfirm
                    title="Remover esta conexão?"
                    description="O túnel é parado e a configuração apagada."
                    okText="Remover"
                    cancelText="Cancelar"
                    onConfirm={() => remove(c.id)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={modalOpen}
        title={
          <Space>
            <SafetyCertificateOutlined />
            {form.id ? "Editar conexão OpenVPN" : "Importar conexão OpenVPN"}
          </Space>
        }
        onCancel={() => setModalOpen(false)}
        onOk={save}
        confirmLoading={saving}
        okText="Salvar e aplicar"
        cancelText="Cancelar"
        width={680}
        destroyOnClose
      >
        <Form layout="vertical" style={{ marginTop: 8 }}>
          <Row gutter={16}>
            <Col span={14}>
              <Form.Item label="Nome" required>
                <Input
                  value={form.name}
                  placeholder="Matriz, Provedor X…"
                  onChange={(e) => patch({ name: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item label="Ativar ao salvar">
                <Switch checked={form.enabled} onChange={(v) => patch({ enabled: v })} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="Descrição (opcional)">
            <Input
              value={form.description}
              onChange={(e) => patch({ description: e.target.value })}
            />
          </Form.Item>

          <Form.Item
            label={
              <Space>
                Perfil .ovpn
                <Upload accept=".ovpn,.conf,.txt,.cfg" showUploadList={false} beforeUpload={readFile}>
                  <Button size="small" icon={<UploadOutlined />}>
                    Importar arquivo
                  </Button>
                </Upload>
              </Space>
            }
            required={!form.id}
          >
            <Input.TextArea
              rows={6}
              value={form.config}
              className="mx-mono"
              placeholder={
                form.id
                  ? "Deixe em branco para manter o perfil atual, ou cole/importe um novo."
                  : "Cole aqui o conteúdo do arquivo .ovpn (com certificados inline)…"
              }
              onChange={(e) => patch({ config: e.target.value, configTouched: true })}
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="Usuário (se exigido)"
                tooltip="Preencha quando o perfil usar auth-user-pass"
              >
                <Input
                  autoComplete="off"
                  value={form.username}
                  onChange={(e) => patch({ username: e.target.value })}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label={`Senha${form.has_password ? " (salva — em branco mantém)" : ""}`}
              >
                <Input.Password
                  autoComplete="new-password"
                  value={form.password}
                  placeholder={form.has_password ? "••••••••" : ""}
                  onChange={(e) => patch({ password: e.target.value })}
                />
              </Form.Item>
            </Col>
          </Row>

          <Card size="small" style={{ marginBottom: 16 }} title={<Space><GlobalOutlined />Roteamento e firewall</Space>}>
            <Row gutter={16} align="middle">
              <Col span={24} style={{ marginBottom: 12 }}>
                <Space>
                  <Switch checked={form.route_lan} onChange={(v) => patch({ route_lan: v })} />
                  <Text>Rotear a rede local (LAN) através deste túnel</Text>
                </Space>
                <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0 44px" }}>
                  Quando ativo, a LAN sai mascarada (NAT) pelo túnel e o firewall libera o
                  encaminhamento. Desligado, apenas o próprio appliance usa o túnel.
                </Paragraph>
              </Col>
              <Col span={12}>
                <Form.Item label="Sub-redes remotas acessíveis" style={{ marginBottom: 8 }}
                  tooltip="Escopo das redes do outro lado que a LAN pode alcançar. Vazio = todas pelo túnel.">
                  <Input
                    value={form.remote_subnets}
                    placeholder="10.50.0.0/24, 172.16.0.0/16"
                    onChange={(e) => patch({ remote_subnets: e.target.value })}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="Sub-redes bloqueadas" style={{ marginBottom: 8 }}
                  tooltip="Destinos que NÃO podem ser alcançados pelo túnel (regra de bloqueio no firewall).">
                  <Input
                    value={form.block_subnets}
                    placeholder="10.50.0.99/32"
                    onChange={(e) => patch({ block_subnets: e.target.value })}
                  />
                </Form.Item>
              </Col>
              <Col span={24}>
                <Space>
                  <Switch
                    checked={form.accept_pushed_routes}
                    onChange={(v) => patch({ accept_pushed_routes: v })}
                  />
                  <Text type="secondary">Aceitar rotas enviadas pelo servidor (recomendado)</Text>
                </Space>
              </Col>
            </Row>
          </Card>
        </Form>
      </Modal>
    </div>
  );
}
