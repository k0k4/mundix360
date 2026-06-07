import { useCallback, useEffect, useState } from "react";
import {
  Tabs,
  Table,
  Button,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Card,
  Row,
  Col,
  Statistic,
  Typography,
  Alert,
  Tooltip,
  message as antdMessage,
} from "antd";
import {
  GlobalOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  CloudServerOutlined,
  BarChartOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader } from "../../components/ui";

const { Text } = Typography;

type Record = { id: string; name: string; ip: string; aliases: string[] };

/* ----------------------------------------------------------- Local records */
function RecordsTab() {
  const [rows, setRows] = useState<Record[]>([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<{ edit: boolean; rec?: Record } | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/network/dns/records");
      setRows(data.records || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    form.resetFields();
    setModal({ edit: false });
  };
  const openEdit = (rec: Record) => {
    form.setFieldsValue({ name: rec.name, ip: rec.ip, aliases: rec.aliases });
    setModal({ edit: true, rec });
  };

  const submit = async () => {
    const v = await form.validateFields();
    const payload = { name: v.name, ip: v.ip, aliases: v.aliases || [] };
    try {
      if (modal?.edit)
        await api.put(
          `/api/network/dns/records/${encodeURIComponent(modal.rec!.name)}`,
          payload,
        );
      else await api.post("/api/network/dns/records", payload);
      antdMessage.success("Registro salvo (dnsmasq recarregado).");
      setModal(null);
      load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar");
    }
  };

  const remove = async (rec: Record) => {
    Modal.confirm({
      title: `Excluir registro ${rec.name}?`,
      okText: "Excluir",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await api.delete(
            `/api/network/dns/records/${encodeURIComponent(rec.name)}`,
          );
          antdMessage.success("Registro excluído.");
          load();
        } catch (e: any) {
          antdMessage.error(e?.response?.data?.detail || "Falha ao excluir");
        }
      },
    });
  };

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Novo registro
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>
          Atualizar
        </Button>
      </Space>
      <Table
        dataSource={rows}
        rowKey="id"
        loading={loading}
        size="middle"
        pagination={false}
      >
        <Table.Column
          title="Nome"
          dataIndex="name"
          render={(n) => <span className="mx-mono">{n}</span>}
        />
        <Table.Column
          title="IP"
          dataIndex="ip"
          render={(i) => <span className="mx-mono">{i}</span>}
        />
        <Table.Column
          title="Aliases"
          dataIndex="aliases"
          render={(a: string[]) =>
            a && a.length ? (
              <Space size={4} wrap>
                {a.map((x) => (
                  <Tag key={x} className="mx-mono">
                    {x}
                  </Tag>
                ))}
              </Space>
            ) : (
              "—"
            )
          }
        />
        <Table.Column
          title="Ações"
          width={120}
          render={(_, r: Record) => (
            <Space>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => openEdit(r)}
              />
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => remove(r)}
              />
            </Space>
          )}
        />
      </Table>

      <Modal
        title={modal?.edit ? "Editar registro DNS" : "Novo registro DNS"}
        open={!!modal}
        onCancel={() => setModal(null)}
        onOk={submit}
        okText="Salvar"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Cria um registro A/AAAA local (host-record). Validado com dnsmasq --test e aplicado com reinício do serviço."
        />
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="Nome (FQDN)"
            rules={[{ required: true, message: "obrigatório" }]}
          >
            <Input
              placeholder="nas.lan.mundix360.local"
              className="mx-mono"
              disabled={modal?.edit}
            />
          </Form.Item>
          <Form.Item
            name="ip"
            label="Endereço IP"
            rules={[{ required: true, message: "obrigatório" }]}
          >
            <Input placeholder="192.168.0.50" className="mx-mono" />
          </Form.Item>
          <Form.Item name="aliases" label="Aliases (opcional)">
            <Select
              mode="tags"
              tokenSeparators={[",", " "]}
              placeholder="storage.lan.mundix360.local"
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

/* ------------------------------------------------------- Upstream resolvers */
function ResolversTab() {
  const [servers, setServers] = useState<string[]>([]);
  const [overview, setOverview] = useState<any>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [r, s] = await Promise.all([
      api.get("/api/network/dns/resolvers"),
      api.get("/api/network/dns/settings"),
    ]);
    setServers((r.data.resolvers || []).map((x: any) => x.server));
    setOverview(s.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/api/network/dns/resolvers", { resolvers: servers });
      antdMessage.success("Resolvers atualizados.");
      load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao salvar");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Row gutter={16}>
      <Col xs={24} lg={12}>
        <Card
          title={
            <Space>
              <CloudServerOutlined /> Resolvers globais (gerenciados)
            </Space>
          }
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Servidores DNS upstream globais (server=). Como o dnsmasq usa no-resolv, defina ao menos um."
          />
          <Select
            mode="tags"
            style={{ width: "100%", marginBottom: 16 }}
            tokenSeparators={[",", " "]}
            value={servers}
            onChange={setServers}
            placeholder="1.1.1.1, 9.9.9.9"
          />
          <Button type="primary" loading={saving} onClick={save}>
            Salvar resolvers
          </Button>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card
          title={
            <Space>
              <GlobalOutlined /> Configuração efetiva (somente leitura)
            </Space>
          }
        >
          {overview && (
            <Space direction="vertical" style={{ width: "100%" }} size={10}>
              <Text>
                Cache:{" "}
                <Tag className="mx-mono">{overview.cache_size || "?"}</Tag>
                no-resolv:{" "}
                <Tag color={overview.no_resolv ? "green" : "default"}>
                  {String(overview.no_resolv)}
                </Tag>
              </Text>
              <Text type="secondary">
                Upstreams detectados em todos os arquivos .conf:
              </Text>
              <Table
                dataSource={overview.upstreams}
                rowKey={(r: any) => `${r.source}-${r.server}`}
                size="small"
                pagination={false}
              >
                <Table.Column
                  title="Server"
                  dataIndex="server"
                  render={(s) => <span className="mx-mono">{s}</span>}
                />
                <Table.Column
                  title="Origem"
                  dataIndex="source"
                  render={(s, r: any) => (
                    <Space>
                      <span className="mx-mono">{s}</span>
                      {r.managed ? (
                        <Tag color="blue">gerenciado</Tag>
                      ) : (
                        <Tag>externo</Tag>
                      )}
                    </Space>
                  )}
                />
              </Table>
            </Space>
          )}
        </Card>
      </Col>
    </Row>
  );
}

/* ----------------------------------------------------------------- Insights */
function InsightsTab() {
  const [stats, setStats] = useState<any>(null);
  const [recent, setRecent] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, r] = await Promise.all([
        api.get("/api/network/dns/stats"),
        api.get("/api/network/dns/recent", { params: { limit: 60 } }),
      ]);
      setStats(s.data);
      setRecent(r.data.recent || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  const win = stats?.window;
  return (
    <Space direction="vertical" style={{ width: "100%" }} size={16}>
      <Space>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          Atualizar
        </Button>
        {win && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            Amostra dos últimos {Math.round((win.bytes_scanned || 0) / 1024)} KB
            de log{" "}
            {win.oldest ? `· ${win.oldest} → ${win.newest}` : ""}
            {win.warning ? ` · ⚠ ${win.warning}` : ""}
          </Text>
        )}
      </Space>

      {win && !win.available && (
        <Alert
          type="warning"
          showIcon
          message="Log de consultas indisponível"
          description={win.warning || "Não foi possível ler o log do dnsmasq."}
        />
      )}

      <Row gutter={16}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="Consultas" value={stats?.total_queries ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="Bloqueadas"
              value={stats?.blocked_total ?? 0}
              valueStyle={{ color: "#f87171" }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="Domínios únicos"
              value={stats?.unique_domains ?? 0}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="Clientes únicos"
              value={stats?.unique_clients ?? 0}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card title="Top domínios" size="small">
            <Table
              dataSource={stats?.top_domains || []}
              rowKey="domain"
              size="small"
              pagination={false}
            >
              <Table.Column
                title="Domínio"
                dataIndex="domain"
                render={(d) => <span className="mx-mono">{d}</span>}
                ellipsis
              />
              <Table.Column title="#" dataIndex="count" width={64} />
            </Table>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="Top clientes" size="small">
            <Table
              dataSource={stats?.top_clients || []}
              rowKey="client"
              size="small"
              pagination={false}
            >
              <Table.Column
                title="Cliente"
                dataIndex="client"
                render={(d) => <span className="mx-mono">{d}</span>}
              />
              <Table.Column title="#" dataIndex="count" width={64} />
            </Table>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card
            title={
              <Space>
                <StopOutlined style={{ color: "#f87171" }} /> Top bloqueados
              </Space>
            }
            size="small"
          >
            <Table
              dataSource={stats?.top_blocked || []}
              rowKey="domain"
              size="small"
              pagination={false}
              locale={{ emptyText: "Nenhum bloqueio na amostra" }}
            >
              <Table.Column
                title="Domínio"
                dataIndex="domain"
                render={(d) => <span className="mx-mono">{d}</span>}
                ellipsis
              />
              <Table.Column title="#" dataIndex="count" width={64} />
            </Table>
          </Card>
        </Col>
      </Row>

      <Card title="Consultas recentes" size="small">
        <Table
          dataSource={recent}
          rowKey={(_, i) => String(i)}
          size="small"
          pagination={{ pageSize: 15 }}
        >
          <Table.Column title="Hora" dataIndex="time" width={130} />
          <Table.Column
            title="Tipo"
            dataIndex="type"
            width={80}
            render={(t) => <Tag>{t}</Tag>}
          />
          <Table.Column
            title="Domínio"
            dataIndex="domain"
            render={(d, r: any) => (
              <Space>
                <span className="mx-mono">{d}</span>
                {r.blocked && <Tag color="red">bloqueado</Tag>}
              </Space>
            )}
            ellipsis
          />
          <Table.Column
            title="Cliente"
            dataIndex="client"
            width={150}
            render={(c) => <span className="mx-mono">{c}</span>}
          />
        </Table>
      </Card>
    </Space>
  );
}

export function DnsPage() {
  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <GlobalOutlined /> Rede · DNS
          </>
        }
        title="Gestão de DNS"
        subtitle="Registros locais, resolvers upstream e observabilidade de consultas do dnsmasq."
      />
      <Tabs
        items={[
          {
            key: "records",
            label: (
              <span>
                <GlobalOutlined /> Registros locais
              </span>
            ),
            children: <RecordsTab />,
          },
          {
            key: "resolvers",
            label: (
              <span>
                <CloudServerOutlined /> Resolvers
              </span>
            ),
            children: <ResolversTab />,
          },
          {
            key: "insights",
            label: (
              <span>
                <BarChartOutlined /> Insights
              </span>
            ),
            children: <InsightsTab />,
          },
        ]}
      />
    </div>
  );
}
