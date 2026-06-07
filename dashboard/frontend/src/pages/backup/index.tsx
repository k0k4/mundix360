import { useCallback, useEffect, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Alert, Typography, Spin, Button, Tooltip,
  Form, Switch, InputNumber, Modal, message, Space, Descriptions,
} from "antd";
import {
  ReloadOutlined, CloudDownloadOutlined, DeleteOutlined, SafetyCertificateOutlined,
  CheckCircleFilled, CloseCircleFilled, DatabaseOutlined, ClockCircleOutlined,
  PlayCircleOutlined, FolderOpenOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text } = Typography;

const fmtBytes = (n: number) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(n) / Math.log(1024));
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${u[i]}`;
};
const fmtDate = (s?: string) =>
  s ? new Date(s).toLocaleString("pt-BR") : "—";

export function BackupPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/backup/overview");
      setData(data);
      form.setFieldsValue({
        enabled: data.schedule?.enabled,
        interval_hours: data.schedule?.interval_hours,
        retention: data.retention,
        include_clickhouse: data.include_clickhouse,
      });
    } finally {
      setLoading(false);
    }
  }, [form]);
  useEffect(() => { load(); }, [load]);

  const runNow = async () => {
    setRunning(true);
    const hide = message.loading("Gerando backup e verificando integridade…", 0);
    try {
      const { data } = await api.post("/api/backup/run");
      hide();
      if (data.verify?.ok) message.success(`Backup criado e verificado: ${data.name}`);
      else message.warning(`Backup criado, mas a verificação falhou: ${data.name}`);
      load();
    } catch (e: any) {
      hide();
      message.error(e?.response?.data?.detail || "Falha ao criar backup");
    } finally {
      setRunning(false);
    }
  };

  const verify = async (name: string) => {
    const hide = message.loading("Verificando…", 0);
    try {
      const { data } = await api.post(`/api/backup/verify/${name}`);
      hide();
      Modal.info({
        title: `Verificação — ${name}`,
        width: 560,
        content: (
          <Table size="small" pagination={false} rowKey="check" dataSource={data.checks}
            style={{ marginTop: 12 }}
            columns={[
              { title: "Checagem", dataIndex: "check" },
              { title: "", dataIndex: "ok", width: 40,
                render: (ok) => ok
                  ? <CheckCircleFilled style={{ color: "#52c41a" }} />
                  : <CloseCircleFilled style={{ color: "#f5222d" }} /> },
              { title: "Detalhe", dataIndex: "detail", ellipsis: true,
                render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text> },
            ]} />
        ),
      });
    } catch {
      hide();
      message.error("Falha na verificação");
    }
  };

  const download = (name: string) => {
    const token = (import.meta as any).env.VITE_API_TOKEN;
    if (token) {
      api.get(`/api/backup/download/${name}`, { responseType: "blob" }).then((r) => {
        const url = URL.createObjectURL(r.data);
        const a = document.createElement("a");
        a.href = url; a.download = name; a.click();
        URL.revokeObjectURL(url);
      });
    } else {
      const a = document.createElement("a");
      a.href = `/api/backup/download/${name}`;
      a.download = name; a.click();
    }
  };

  const remove = (name: string) => {
    Modal.confirm({
      title: "Excluir backup?",
      content: name,
      okType: "danger",
      onOk: async () => {
        await api.delete(`/api/backup/${name}`);
        message.success("Backup excluído");
        load();
      },
    });
  };

  const extract = async (name: string) => {
    const hide = message.loading("Extraindo para inspeção…", 0);
    try {
      const { data } = await api.post(`/api/backup/extract/${name}`);
      hide();
      Modal.success({
        title: "Extraído para inspeção (sem aplicar)",
        content: <Text code>{data.path}</Text>,
      });
    } catch {
      hide();
      message.error("Falha ao extrair");
    }
  };

  const saveSchedule = async (v: any) => {
    try {
      await api.put("/api/backup/schedule", v);
      message.success("Agendamento salvo");
      load();
    } catch {
      message.error("Falha ao salvar");
    }
  };

  if (loading && !data) return <Spin style={{ display: "block", margin: "80px auto" }} />;

  const backups: any[] = data?.backups || [];
  const lastOk = data?.last_status === "ok";

  return (
    <div className="mx-page">
      <PageHeader
        eyebrow="Sistema · Backup"
        title="Backup & Restauração"
        subtitle="Snapshots verificados das configurações (firewall, DNS/DHCP, WAF), estado do painel, memória da IA e histórico do SIEM."
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>Atualizar</Button>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={runNow}>
              Gerar backup agora
            </Button>
          </Space>
        }
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={6}>
          <KpiCard icon={<DatabaseOutlined />} color="#1677ff"
            label="Backups armazenados" value={String(data?.count || 0)} />
        </Col>
        <Col xs={24} sm={6}>
          <KpiCard icon={<FolderOpenOutlined />} color="#722ed1"
            label="Espaço utilizado" value={fmtBytes(data?.total_size || 0)} />
        </Col>
        <Col xs={24} sm={6}>
          <KpiCard icon={lastOk ? <CheckCircleFilled /> : <CloseCircleFilled />}
            color={lastOk ? "#52c41a" : data?.last_status ? "#f5222d" : "#8c8c8c"}
            label="Último backup"
            value={data?.last_status ? (lastOk ? "Verificado" : "Verificação falhou") : "Nenhum"} />
        </Col>
        <Col xs={24} sm={6}>
          <KpiCard icon={<ClockCircleOutlined />} color="#fa8c16"
            label="Executado em" value={data?.last_run ? fmtDate(data.last_run) : "—"} />
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="Agendamento & retenção" bordered={false} className="mx-card">
            <Form form={form} layout="vertical" onFinish={saveSchedule}>
              <Form.Item name="enabled" label="Backup automático" valuePropName="checked">
                <Switch checkedChildren="On" unCheckedChildren="Off" />
              </Form.Item>
              <Form.Item name="interval_hours" label="Intervalo (horas)"
                rules={[{ required: true }]}>
                <InputNumber min={1} max={720} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="retention" label="Manter últimos (qtd)"
                rules={[{ required: true }]}>
                <InputNumber min={1} max={365} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="include_clickhouse" label="Incluir histórico do SIEM (ClickHouse)"
                valuePropName="checked"
                tooltip="Dump da tabela akvorado.siem_alerts. Aumenta o tamanho do backup.">
                <Switch checkedChildren="Sim" unCheckedChildren="Não" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block>Salvar</Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message="Restauração é uma decisão do operador"
            description="Por segurança (risco de lock-out), a restauração NÃO é aplicada automaticamente. Use 'Verificar' para validar a integridade, 'Baixar' para guardar fora do appliance ou 'Inspecionar' para extrair o conteúdo a uma pasta de staging e aplicar manualmente." />

          <Card title="Backups disponíveis" bordered={false} className="mx-card">
            <Table size="small" rowKey="name" dataSource={backups}
              pagination={{ pageSize: 8, size: "small" }}
              expandable={{
                expandedRowRender: (r) => (
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="Conteúdo">
                      {(r.manifest?.contents || []).map((c: string) => (
                        <Tag key={c} style={{ marginBottom: 4 }}>{c}</Tag>
                      ))}
                    </Descriptions.Item>
                    {r.manifest?.clickhouse && (
                      <Descriptions.Item label="SIEM (ClickHouse)">
                        {r.manifest.clickhouse.rows?.toLocaleString("pt-BR")} alertas
                      </Descriptions.Item>
                    )}
                    {r.manifest?.clickhouse_error && (
                      <Descriptions.Item label="Erro ClickHouse">
                        <Text type="danger">{r.manifest.clickhouse_error}</Text>
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                ),
              }}
              columns={[
                { title: "Arquivo", dataIndex: "name", ellipsis: true,
                  render: (v) => <Text code style={{ fontSize: 12 }}>{v}</Text> },
                { title: "Criado", dataIndex: "created", width: 160,
                  render: (v) => <Text type="secondary" style={{ fontSize: 12 }}>{fmtDate(v)}</Text> },
                { title: "Tamanho", dataIndex: "size", width: 90, align: "right",
                  render: (v) => <Tag>{fmtBytes(v)}</Tag> },
                { title: "Ações", width: 170, align: "right",
                  render: (_, r) => (
                    <Space size={4}>
                      <Tooltip title="Verificar integridade">
                        <Button size="small" icon={<SafetyCertificateOutlined />}
                          onClick={() => verify(r.name)} />
                      </Tooltip>
                      <Tooltip title="Inspecionar (staging)">
                        <Button size="small" icon={<FolderOpenOutlined />}
                          onClick={() => extract(r.name)} />
                      </Tooltip>
                      <Tooltip title="Baixar">
                        <Button size="small" icon={<CloudDownloadOutlined />}
                          onClick={() => download(r.name)} />
                      </Tooltip>
                      <Tooltip title="Excluir">
                        <Button size="small" danger icon={<DeleteOutlined />}
                          onClick={() => remove(r.name)} />
                      </Tooltip>
                    </Space>
                  ) },
              ]} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
