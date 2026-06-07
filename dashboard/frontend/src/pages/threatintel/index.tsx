import { useCallback, useEffect, useState } from "react";
import {
  Tabs, Button, Space, Tag, Card, Row, Col, Alert, Typography, Tooltip,
  Spin, Switch, Input, InputNumber, Form, message as antdMessage,
} from "antd";
import {
  ReloadOutlined, SafetyCertificateOutlined, CheckCircleFilled,
  WarningOutlined, ClockCircleOutlined, CloudDownloadOutlined,
  ThunderboltOutlined, AimOutlined, BugOutlined, ApiOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text, Paragraph } = Typography;

const fmtNum = (n: number) => (n ?? 0).toLocaleString("pt-BR");
const fmtDate = (s?: string | null) =>
  s ? new Date(s).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

const CAT_META: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  c2: { color: "#f5222d", label: "C2 / Malware", icon: <BugOutlined /> },
  hijacked: { color: "#fa8c16", label: "Redes sequestradas", icon: <AimOutlined /> },
  compromised: { color: "#faad14", label: "Hosts comprometidos", icon: <ThunderboltOutlined /> },
  attackers: { color: "#722ed1", label: "Atacantes", icon: <SafetyCertificateOutlined /> },
};

/* ===================================================== Feeds =============== */
function FeedsTab() {
  const [ov, setOv] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    const { data } = await api.get("/api/threatintel/overview");
    setOv(data);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (fid: string, enabled: boolean) => {
    setBusy(fid);
    try {
      await api.post(`/api/threatintel/feeds/${fid}/toggle`, { enabled });
      msg.success(enabled ? "Feed ativado e aplicado" : "Feed desativado");
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao alternar feed");
    } finally {
      setBusy(null);
      load();
    }
  };

  const updateAll = async () => {
    setBusy("__all__");
    try {
      const { data } = await api.post("/api/threatintel/update", {});
      msg.success(`Atualizado — ${fmtNum(data.blocked_count)} redes bloqueadas`);
      (data.warnings || []).forEach((w: string) => msg.warning(w));
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao atualizar feeds");
    } finally {
      setBusy(null);
      load();
    }
  };

  if (loading) return <Spin style={{ display: "block", margin: "80px auto" }} />;
  const feeds: any[] = ov?.feeds || [];
  const active = feeds.filter((f) => f.enabled).length;

  return (
    <>
      {ctx}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={8}>
          <KpiCard icon={<SafetyCertificateOutlined />} color="#f5222d"
            label="Redes bloqueadas" value={fmtNum(ov?.blocked_count || 0)} />
        </Col>
        <Col xs={24} sm={8}>
          <KpiCard icon={<ApiOutlined />} color="#1677ff"
            label="Feeds ativos" value={`${active} / ${feeds.length}`} />
        </Col>
        <Col xs={24} sm={8}>
          <KpiCard icon={<ClockCircleOutlined />} color="#52c41a"
            label="Última aplicação" value={fmtDate(ov?.last_apply)} />
        </Col>
      </Row>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="Bloqueio proativo por reputação"
        description="IPs/redes maliciosas conhecidas (C2 de malware, botnets, redes sequestradas e atacantes) são baixadas de fontes públicas e bloqueadas no firewall (nftables) antes mesmo de qualquer detecção interna. Apenas endereços globalmente roteáveis entram no bloqueio — faixas internas/privadas nunca são afetadas." />

      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <Button type="primary" icon={<CloudDownloadOutlined />}
          loading={busy === "__all__"} onClick={updateAll}>
          Atualizar todos os feeds agora
        </Button>
      </div>

      <Row gutter={[16, 16]}>
        {feeds.map((f) => {
          const cm = CAT_META[f.category] || { color: "#888", label: f.category, icon: <ApiOutlined /> };
          return (
            <Col xs={24} md={12} key={f.id}>
              <Card bordered={false} className="mx-card"
                styles={{ body: { padding: 18 } }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                  <div className="mx-kpi-icon" style={{ background: `${cm.color}1f`, color: cm.color }}>
                    {cm.icon}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Space size={8} wrap>
                      <Text strong>{f.name}</Text>
                      <Tag color={cm.color}>{cm.label}</Tag>
                      {f.enabled
                        ? <Tag icon={<CheckCircleFilled />} color="success">ativo</Tag>
                        : <Tag>inativo</Tag>}
                    </Space>
                    <Paragraph type="secondary" style={{ margin: "6px 0 8px", fontSize: 13 }}>
                      {f.description}
                    </Paragraph>
                    <Space size={16} wrap>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {fmtNum(f.count)} entradas
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        <ClockCircleOutlined /> {fmtDate(f.last_updated)}
                      </Text>
                      {f.last_error && (
                        <Tooltip title={f.last_error}>
                          <Tag icon={<WarningOutlined />} color="error">erro</Tag>
                        </Tooltip>
                      )}
                    </Space>
                  </div>
                  <Switch checked={f.enabled} loading={busy === f.id}
                    onChange={(v) => toggle(f.id, v)} />
                </div>
              </Card>
            </Col>
          );
        })}
      </Row>
    </>
  );
}

/* ============================================== Exceções / Egress ========= */
function PolicyTab() {
  const [ov, setOv] = useState<any>(null);
  const [allow, setAllow] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    const { data } = await api.get("/api/threatintel/overview");
    setOv(data);
    setAllow((data.allowlist || []).join("\n"));
  }, []);
  useEffect(() => { load(); }, [load]);

  const saveAllow = async () => {
    setSaving(true);
    try {
      const entries = allow.split("\n").map((s) => s.trim()).filter(Boolean);
      await api.put("/api/threatintel/allowlist", { entries });
      msg.success("Exceções salvas e aplicadas");
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao salvar exceções");
    } finally {
      setSaving(false);
    }
  };

  const setEgress = async (v: boolean) => {
    try {
      await api.put("/api/threatintel/egress", { block_egress: v });
      msg.success(v ? "Bloqueio de saída ativado" : "Bloqueio de saída desativado");
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha");
    }
  };

  if (!ov) return <Spin style={{ display: "block", margin: "80px auto" }} />;

  return (
    <>
      {ctx}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={14}>
          <Card title="Exceções (allowlist)" bordered={false} className="mx-card">
            <Paragraph type="secondary" style={{ fontSize: 13 }}>
              IPs ou redes (CIDR) que <Text strong>nunca</Text> devem ser bloqueados pelos feeds —
              um por linha. Útil para parceiros/serviços legítimos que apareçam erroneamente em uma
              lista. Endereços privados não são aceitos (já nunca são bloqueados).
              <br />
              <Text type="warning">
                Observação: estas exceções valem apenas para os feeds de Threat Intelligence,
                não para o bloqueio manual de IP.
              </Text>
            </Paragraph>
            <Input.TextArea rows={10} value={allow}
              onChange={(e) => setAllow(e.target.value)}
              placeholder={"203.0.113.10\n198.18.0.0/16"} style={{ fontFamily: "monospace" }} />
            <Button type="primary" style={{ marginTop: 12 }} loading={saving} onClick={saveAllow}>
              Salvar exceções
            </Button>
          </Card>
        </Col>
        <Col xs={24} md={10}>
          <Card title="Bloqueio de saída (egress)" bordered={false} className="mx-card">
            <Paragraph type="secondary" style={{ fontSize: 13 }}>
              Além de barrar conexões <Text strong>de entrada</Text> vindas de IPs maliciosos,
              também bloqueia <Text strong>saídas</Text> dos hosts internos para esses IPs
              (proteção anti-C2 / exfiltração).
            </Paragraph>
            <Alert type="warning" showIcon style={{ marginBottom: 12 }}
              message="Pode gerar falsos positivos"
              description="Listas de hosts comprometidos podem conter IPs de nuvem/CDN compartilhados. Se notar quebras de tráfego legítimo, desative." />
            <Space>
              <Switch checked={!!ov.block_egress} onChange={setEgress} />
              <Text>{ov.block_egress ? "Ativado" : "Desativado"}</Text>
            </Space>
          </Card>
        </Col>
      </Row>
    </>
  );
}

/* =================================================== Agendamento ========== */
function ScheduleTab() {
  const [sched, setSched] = useState<any>(null);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    const { data } = await api.get("/api/threatintel/schedule");
    setSched(data);
    form.setFieldsValue(data);
  }, [form]);
  useEffect(() => { load(); }, [load]);

  const save = async (vals: any) => {
    try {
      await api.put("/api/threatintel/schedule", vals);
      msg.success("Agendamento salvo");
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao salvar");
    }
  };

  if (!sched) return <Spin style={{ display: "block", margin: "80px auto" }} />;

  return (
    <>
      {ctx}
      <Card title="Atualização automática" bordered={false} className="mx-card"
        style={{ maxWidth: 520 }}>
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          Os feeds são rebaixados e reaplicados periodicamente para manter o bloqueio atualizado.
        </Paragraph>
        <Form form={form} layout="vertical" onFinish={save} initialValues={sched}>
          <Form.Item name="enabled" label="Atualização automática" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="interval_hours" label="Intervalo (horas)"
            rules={[{ required: true }]}>
            <InputNumber min={1} max={168} style={{ width: 160 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<ReloadOutlined />}>
            Salvar agendamento
          </Button>
        </Form>
      </Card>
    </>
  );
}

/* ===================================================== Page =============== */
export function ThreatIntelPage() {
  return (
    <div className="mx-page">
      <PageHeader
        eyebrow="Firewall · Threat Intelligence"
        title="Threat Intelligence"
        subtitle="Bloqueio proativo de IPs e redes maliciosas conhecidas (IOC em tempo real)."
      />
      <Tabs
        items={[
          { key: "feeds", label: "Feeds", children: <FeedsTab /> },
          { key: "policy", label: "Exceções & Egress", children: <PolicyTab /> },
          { key: "schedule", label: "Agendamento", children: <ScheduleTab /> },
        ]}
      />
    </div>
  );
}
