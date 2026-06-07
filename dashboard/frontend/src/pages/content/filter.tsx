import { useCallback, useEffect, useState } from "react";
import {
  Tabs, Table, Button, Space, Tag, Modal, Form, Input, Select, Switch,
  Card, Row, Col, Popconfirm, Alert, Typography, Tooltip, Spin, Empty,
  InputNumber, message as antdMessage,
} from "antd";
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, GlobalOutlined,
  SafetyCertificateOutlined, CheckCircleFilled, WarningOutlined,
  ClockCircleOutlined, CloudDownloadOutlined, ApiOutlined,
  StopOutlined, CheckCircleOutlined, EyeOutlined, PauseCircleOutlined,
  PlayCircleOutlined, DesktopOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text, Paragraph } = Typography;

const fmtNum = (n: number) => n.toLocaleString("pt-BR");
const fmtDate = (s?: string | null) =>
  s ? new Date(s).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

/* ===================================================== Categorias ======== */
function CategoriesTab() {
  const [ov, setOv] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    const { data } = await api.get("/api/content/overview");
    setOv(data);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (cid: string, enabled: boolean) => {
    setBusy(cid);
    try {
      await api.post(`/api/content/categories/${cid}/toggle`, { enabled });
      msg.success(enabled ? "Categoria ativada e baixada" : "Categoria desativada");
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao alternar categoria");
    } finally {
      setBusy(null);
      load();
    }
  };

  const updateOne = async (cid: string) => {
    setBusy(cid);
    try {
      await api.post(`/api/content/categories/${cid}/update`);
      msg.success("Lista atualizada");
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao atualizar");
    } finally {
      setBusy(null);
      load();
    }
  };

  const updateAll = async () => {
    setBusy("__all__");
    try {
      await api.post("/api/content/categories/update-all");
      msg.success("Atualização concluída");
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao atualizar");
    } finally {
      setBusy(null);
      load();
    }
  };

  if (loading) return <div style={{ padding: 48, textAlign: "center" }}><Spin /></div>;

  return (
    <>
      {ctx}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<SafetyCertificateOutlined />} color="#22c55e"
            label="Categorias ativas" value={ov.enabled_categories} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<GlobalOutlined />} color="#3b82f6"
            label="Domínios bloqueados" value={fmtNum(ov.total_blocked)} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CheckCircleFilled />} color="#a855f7"
            label="Exceções (allowlist)" value={ov.allowlist_count} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<ClockCircleOutlined />} color="#f59e0b"
            label="Atualização automática"
            value={ov.schedule?.enabled ? `${ov.schedule.interval_hours}h` : "off"} />
        </Col>
      </Row>

      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}
        wrap>
        <Text type="secondary">
          As listas são baixadas de repositórios mantidos publicamente e bloqueiam o
          domínio e todos os subdomínios via DNS sinkhole.
        </Text>
        <Button icon={<CloudDownloadOutlined />} loading={busy === "__all__"}
          onClick={updateAll}>
          Atualizar todas as ativas
        </Button>
      </Space>

      {ov.running && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message={`Atualização em andamento${ov.current ? ` (${ov.current})` : ""}…`} />
      )}

      <Row gutter={[16, 16]}>
        {ov.categories.map((c: any) => (
          <Col xs={24} sm={12} lg={8} key={c.id}>
            <Card bordered={false} className="mx-kpi"
              style={{ ["--mx-kpi-accent" as any]: `${c.color}22`, opacity: c.enabled ? 1 : 0.72 }}
              styles={{ body: { padding: 18 } }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <Space>
                  <div className="mx-kpi-icon" style={{ background: `${c.color}1f`, color: c.color }}>
                    <GlobalOutlined />
                  </div>
                  <div>
                    <div style={{ fontWeight: 600 }}>{c.label}</div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {c.active_source_count}/{c.source_count} fontes
                    </Text>
                  </div>
                </Space>
                <Switch checked={c.enabled} loading={busy === c.id}
                  onChange={(v) => toggle(c.id, v)} />
              </div>

              <div style={{ marginTop: 14, display: "flex", justifyContent: "space-between",
                alignItems: "flex-end" }}>
                <div>
                  <div style={{ fontSize: 22, fontWeight: 700 }}>
                    {fmtNum(c.domain_count)}
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>domínios</Text>
                </div>
                <div style={{ textAlign: "right" }}>
                  <Tooltip title={`Última atualização: ${fmtDate(c.last_success)}`}>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      <ClockCircleOutlined /> {fmtDate(c.last_success)}
                    </Text>
                  </Tooltip>
                  <div style={{ marginTop: 6 }}>
                    <Button size="small" icon={<ReloadOutlined />}
                      loading={busy === c.id} disabled={!c.enabled}
                      onClick={() => updateOne(c.id)}>
                      Atualizar
                    </Button>
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 10, minHeight: 22 }}>
                {c.large && <Tag color="orange">Lista grande</Tag>}
                {c.truncated && <Tag color="red">Truncada</Tag>}
                {c.error && (
                  <Tooltip title={c.error}>
                    <Tag color="red" icon={<WarningOutlined />}>Erro parcial</Tag>
                  </Tooltip>
                )}
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </>
  );
}

/* ================================================= Bloqueio manual ======= */
function ManualTab() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await api.get("/api/content/blocklist");
    setRows(data.domains.map((d: any, i: number) => ({ ...d, id: d.domain || i })));
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const add = () => form.validateFields().then(async (v) => {
    try {
      await api.post("/api/content/blocklist", v);
      msg.success(`Domínio ${v.domain} bloqueado`);
      setOpen(false); form.resetFields(); load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha");
    }
  });

  const remove = async (domain: string) => {
    await api.delete(`/api/content/blocklist/${encodeURIComponent(domain)}`);
    msg.success("Domínio desbloqueado"); load();
  };

  return (
    <>
      {ctx}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          Bloquear domínio
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>Recarregar</Button>
      </Space>
      <Table dataSource={rows} rowKey="id" loading={loading} size="middle"
        pagination={{ pageSize: 15 }}>
        <Table.Column title="Domínio" dataIndex="domain"
          render={(d) => <Space><GlobalOutlined style={{ color: "#fa8c16" }} />
            <span className="mx-mono">{d}</span></Space>} />
        <Table.Column title="Nota" dataIndex="note" />
        <Table.Column title="Ações" width={90}
          render={(_, r: any) => (
            <Popconfirm title={`Desbloquear ${r.domain}?`} onConfirm={() => remove(r.domain)}>
              <Button danger size="small" icon={<DeleteOutlined />} />
            </Popconfirm>
          )} />
      </Table>
      <Modal title="Bloquear domínio" open={open} onOk={add}
        onCancel={() => setOpen(false)} okText="Bloquear">
        <Form form={form} layout="vertical">
          <Form.Item name="domain" label="Domínio"
            rules={[{ required: true, message: "Informe o domínio" }]}>
            <Input placeholder="exemplo.com" className="mx-mono" />
          </Form.Item>
          <Form.Item name="note" label="Nota / categoria">
            <Input placeholder="malware, adulto, ..." />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

/* =================================================== Exceções ============ */
function AllowlistTab() {
  const [domains, setDomains] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await api.get("/api/content/allowlist");
    setDomains(data.domains);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (next: string[]) => {
    setSaving(true);
    try {
      await api.put("/api/content/allowlist", { domains: next });
      setDomains(next);
      msg.success("Exceções atualizadas");
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha");
    } finally { setSaving(false); }
  };

  const add = () => form.validateFields().then((v) => {
    save([...new Set([...domains, v.domain.trim().toLowerCase()])]);
    setOpen(false); form.resetFields();
  });

  return (
    <>
      {ctx}
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="Exceções sobrepõem qualquer bloqueio"
        description="Domínios aqui resolvem normalmente mesmo que estejam em uma categoria bloqueada (via server=/dominio/#)." />
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          Adicionar exceção
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>Recarregar</Button>
      </Space>
      {loading ? <Spin /> : domains.length === 0 ? (
        <Empty description="Nenhuma exceção" />
      ) : (
        <Space wrap>
          {domains.map((d) => (
            <Tag key={d} closable color="green"
              onClose={(e) => { e.preventDefault(); save(domains.filter((x) => x !== d)); }}
              style={{ padding: "4px 10px", fontSize: 13 }}>
              <CheckCircleFilled /> <span className="mx-mono">{d}</span>
            </Tag>
          ))}
        </Space>
      )}
      <Modal title="Adicionar exceção" open={open} onOk={add} confirmLoading={saving}
        onCancel={() => setOpen(false)} okText="Adicionar">
        <Form form={form} layout="vertical">
          <Form.Item name="domain" label="Domínio"
            rules={[{ required: true, message: "Informe o domínio" }]}>
            <Input placeholder="site-permitido.com" className="mx-mono" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

/* ===================================================== Fontes ============ */
function SourcesTab() {
  const [sources, setSources] = useState<any[]>([]);
  const [cats, setCats] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await api.get("/api/content/catalog");
    setSources(data.sources);
    setCats(data.categories);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (sid: string, enabled: boolean) => {
    await api.post(`/api/content/sources/${sid}/toggle`, { enabled });
    load();
  };
  const add = () => form.validateFields().then(async (v) => {
    try {
      await api.post("/api/content/sources", v);
      msg.success("Fonte adicionada"); setOpen(false); form.resetFields(); load();
    } catch (e: any) { msg.error(e?.response?.data?.detail || "Falha"); }
  });
  const del = async (sid: string) => {
    await api.delete(`/api/content/sources/${sid}`); msg.success("Fonte removida"); load();
  };

  return (
    <>
      {ctx}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          Adicionar fonte
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>Recarregar</Button>
      </Space>
      <Table dataSource={sources} rowKey="id" loading={loading} size="middle"
        pagination={false}>
        <Table.Column title="Fonte" dataIndex="name"
          render={(n, r: any) => (
            <Space direction="vertical" size={0}>
              <Space><ApiOutlined /> <b>{n}</b>{r.custom && <Tag>custom</Tag>}</Space>
              <Text type="secondary" style={{ fontSize: 12 }}>{r.description}</Text>
            </Space>
          )} />
        <Table.Column title="Categoria" dataIndex="category"
          render={(c) => <Tag color={cats[c]?.color}>{cats[c]?.label || c}</Tag>} />
        <Table.Column title="Formato" dataIndex="format"
          render={(f) => <Tag>{f}</Tag>} />
        <Table.Column title="Ativa" dataIndex="enabled" width={80}
          render={(e, r: any) => <Switch checked={e} size="small"
            onChange={(v) => toggle(r.id, v)} />} />
        <Table.Column title="" width={60}
          render={(_, r: any) => r.custom && (
            <Popconfirm title="Remover fonte?" onConfirm={() => del(r.id)}>
              <Button danger size="small" icon={<DeleteOutlined />} />
            </Popconfirm>
          )} />
      </Table>
      <Modal title="Adicionar fonte personalizada" open={open} onOk={add}
        onCancel={() => setOpen(false)} okText="Adicionar">
        <Form form={form} layout="vertical">
          <Form.Item name="id" label="ID" rules={[{ required: true },
            { pattern: /^[a-z0-9][a-z0-9_-]{0,40}$/, message: "a-z, 0-9, _-" }]}>
            <Input placeholder="minha-lista" className="mx-mono" />
          </Form.Item>
          <Form.Item name="name" label="Nome">
            <Input placeholder="Minha lista personalizada" />
          </Form.Item>
          <Form.Item name="category" label="Categoria" rules={[{ required: true }]}>
            <Select options={Object.entries(cats).map(([k, v]: any) =>
              ({ value: k, label: v.label }))} />
          </Form.Item>
          <Form.Item name="format" label="Formato" initialValue="hosts"
            rules={[{ required: true }]}>
            <Select options={[
              { value: "hosts", label: "hosts (0.0.0.0 dominio)" },
              { value: "domains", label: "domains (um por linha)" },
              { value: "adblock", label: "adblock (||dominio^)" },
            ]} />
          </Form.Item>
          <Form.Item name="url" label="URL" rules={[{ required: true, type: "url" }]}>
            <Input placeholder="https://..." className="mx-mono" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

/* ================================================= Agendamento =========== */
function ScheduleTab() {
  const [sched, setSched] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    const { data } = await api.get("/api/content/schedule");
    setSched(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (patch: any) => {
    const next = { ...sched, ...patch };
    setSaving(true);
    try {
      const { data } = await api.put("/api/content/schedule", {
        enabled: next.enabled, interval_hours: next.interval_hours });
      setSched(data); msg.success("Agendamento salvo");
    } catch (e: any) { msg.error(e?.response?.data?.detail || "Falha"); }
    finally { setSaving(false); }
  };

  if (!sched) return <Spin />;
  return (
    <>
      {ctx}
      <Card bordered={false} style={{ maxWidth: 520 }}>
        <Paragraph type="secondary">
          Quando ativo, as categorias habilitadas são rebaixadas automaticamente no
          intervalo definido. A última execução: <b>{fmtDate(sched.last_run)}</b>.
        </Paragraph>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Space>
            <Switch checked={sched.enabled} loading={saving}
              onChange={(v) => save({ enabled: v })} />
            <Text>Atualização automática</Text>
          </Space>
          <Space>
            <Text>Intervalo (horas):</Text>
            <InputNumber min={1} max={720} value={sched.interval_hours}
              onChange={(v) => setSched({ ...sched, interval_hours: v })}
              onBlur={() => save({ interval_hours: sched.interval_hours })} />
          </Space>
        </Space>
      </Card>
    </>
  );
}

/* =================================================== Tempo real ========= */
const fmtTime = (ms?: number | null) =>
  ms ? new Date(ms).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" }) : "—";

function LiveQueriesTab() {
  const [stats, setStats] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [available, setAvailable] = useState(true);
  const [live, setLive] = useState(true);
  const [search, setSearch] = useState("");
  const [statusF, setStatusF] = useState<string>("");
  const [typeF, setTypeF] = useState<string>("");
  const [clientF, setClientF] = useState<string>("");
  const [limit, setLimit] = useState(200);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async (showSpin = false) => {
    if (showSpin) setLoading(true);
    try {
      const params = { search, status: statusF, qtype: typeF, client: clientF, limit };
      const [q, s] = await Promise.all([
        api.get("/api/content/queries", { params }),
        api.get("/api/content/queries/stats"),
      ]);
      setAvailable(q.data.available !== false);
      setEvents((q.data.events || []).map((e: any, i: number) => ({ ...e, _k: `${e.ts}-${e.domain}-${i}` })));
      setTotal(q.data.total || 0);
      setStats(s.data);
    } catch {
      /* keep previous data on transient errors */
    } finally {
      setLoading(false);
    }
  }, [search, statusF, typeF, clientF, limit]);

  useEffect(() => { load(true); }, [load]);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => load(false), 5000);
    return () => clearInterval(t);
  }, [live, load]);

  const blockDomain = async (domain: string) => {
    try {
      await api.post("/api/content/blocklist", { domain, note: "via monitor" });
      msg.success(`${domain} bloqueado`);
      load(false);
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao bloquear");
    }
  };

  const allowDomain = async (domain: string) => {
    try {
      const { data } = await api.get("/api/content/allowlist");
      const current: string[] = data.domains || [];
      if (current.includes(domain)) { msg.info("Já está nas exceções"); return; }
      await api.put("/api/content/allowlist", { domains: [...current, domain] });
      msg.success(`${domain} liberado (exceção)`);
      load(false);
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao liberar");
    }
  };

  const clientOptions = stats?.top_clients?.map((c: any) => ({ value: c.key, label: c.key })) || [];

  if (!available) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <span>
            Log de consultas DNS indisponível.<br />
            <Text type="secondary">
              Verifique se o dnsmasq tem <span className="mx-mono">log-queries</span> e{" "}
              <span className="mx-mono">log-facility=/var/log/dnsmasq/dnsmasq.log</span> habilitados.
            </Text>
          </span>
        }
        style={{ padding: 48 }}
      />
    );
  }

  return (
    <>
      {ctx}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<EyeOutlined />} color="#1677ff" label="Consultas (janela)"
            value={fmtNum(stats?.total || 0)} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<StopOutlined />} color="#ff4d4f" label="Bloqueadas"
            value={fmtNum(stats?.blocked || 0)} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<CheckCircleFilled />} color="#52c41a" label="Permitidas"
            value={fmtNum(stats?.allowed || 0)} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<SafetyCertificateOutlined />} color="#fa8c16" label="Taxa de bloqueio"
            value={stats?.block_rate ?? 0} suffix="%" />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card size="small" title={<><StopOutlined style={{ color: "#ff4d4f" }} /> Mais bloqueados</>}
            bordered={false} className="mx-card">
            {stats?.top_blocked?.length ? stats.top_blocked.map((d: any) => (
              <div key={d.key} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                <span className="mx-mono">{d.key}</span>
                <Tag color="red">{fmtNum(d.count)}</Tag>
              </div>
            )) : <Text type="secondary">Nenhum bloqueio na janela.</Text>}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card size="small" title={<><DesktopOutlined style={{ color: "#1677ff" }} /> Top clientes</>}
            bordered={false} className="mx-card">
            {stats?.top_clients?.length ? stats.top_clients.map((d: any) => (
              <div key={d.key} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                <span className="mx-mono">{d.key}</span>
                <Tag>{fmtNum(d.count)}</Tag>
              </div>
            )) : <Text type="secondary">Sem dados.</Text>}
          </Card>
        </Col>
      </Row>

      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search allowClear placeholder="Buscar domínio…" style={{ width: 220 }}
          onSearch={setSearch} onChange={(e) => !e.target.value && setSearch("")} />
        <Select allowClear placeholder="Status" style={{ width: 140 }} value={statusF || undefined}
          onChange={(v) => setStatusF(v || "")}
          options={[{ value: "blocked", label: "Bloqueadas" }, { value: "allowed", label: "Permitidas" }]} />
        <Select allowClear placeholder="Tipo" style={{ width: 120 }} value={typeF || undefined}
          onChange={(v) => setTypeF(v || "")}
          options={["A", "AAAA", "HTTPS", "PTR", "SRV", "TXT", "MX", "CNAME"].map((t) => ({ value: t, label: t }))} />
        <Select allowClear showSearch placeholder="Cliente" style={{ width: 180 }} value={clientF || undefined}
          onChange={(v) => setClientF(v || "")} options={clientOptions} />
        <Select value={limit} style={{ width: 130 }} onChange={setLimit}
          options={[100, 200, 500, 1000].map((n) => ({ value: n, label: `${n} linhas` }))} />
        <Tooltip title={live ? "Pausar atualização ao vivo" : "Retomar atualização ao vivo"}>
          <Button icon={live ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            type={live ? "primary" : "default"} onClick={() => setLive((v) => !v)}>
            {live ? "Ao vivo" : "Pausado"}
          </Button>
        </Tooltip>
        <Button icon={<ReloadOutlined />} onClick={() => load(true)}>Atualizar</Button>
      </Space>

      <Table dataSource={events} rowKey="_k" loading={loading} size="small"
        pagination={{ pageSize: 25, showSizeChanger: false }}
        footer={() => <Text type="secondary">{fmtNum(total)} consultas correspondem aos filtros (janela recente do log).</Text>}>
        <Table.Column title="Horário" dataIndex="ts" width={170}
          render={(ts) => <span className="mx-mono" style={{ fontSize: 12 }}>{fmtTime(ts)}</span>} />
        <Table.Column title="Cliente" dataIndex="client" width={140}
          render={(c) => <span className="mx-mono">{c}</span>} />
        <Table.Column title="Tipo" dataIndex="type" width={70}
          render={(t) => <Tag>{t}</Tag>} />
        <Table.Column title="Domínio" dataIndex="domain"
          render={(d) => <Space><GlobalOutlined style={{ color: "#8c8c8c" }} />
            <span className="mx-mono">{d}</span></Space>} />
        <Table.Column title="Status" dataIndex="status" width={120}
          render={(s) => s === "blocked"
            ? <Tag color="red" icon={<StopOutlined />}>Bloqueado</Tag>
            : <Tag color="green" icon={<CheckCircleOutlined />}>Permitido</Tag>} />
        <Table.Column title="Ações" width={110}
          render={(_, r: any) => r.status === "blocked"
            ? <Popconfirm title={`Liberar ${r.domain}?`} onConfirm={() => allowDomain(r.domain)}>
                <Button size="small" icon={<CheckCircleOutlined />}>Liberar</Button>
              </Popconfirm>
            : <Popconfirm title={`Bloquear ${r.domain}?`} onConfirm={() => blockDomain(r.domain)}>
                <Button size="small" danger icon={<StopOutlined />}>Bloquear</Button>
              </Popconfirm>} />
      </Table>
    </>
  );
}

/* ====================================================== Page ============= */
export const ContentFilterPage = () => (
  <div>
    <PageHeader
      eyebrow={<><SafetyCertificateOutlined /> DNS Sinkhole</>}
      title="Filtro de Conteúdo"
      subtitle="Bloqueio por categoria, listas atualizáveis, exceções e agendamento."
    />
    <Alert type="warning" showIcon style={{ marginBottom: 16 }}
      message="DNS-over-HTTPS pode contornar o filtro"
      description="O bloqueio atua no DNS local. Para máxima eficácia, bloqueie DoH/DoT no firewall e force os clientes a usar este resolvedor." />
    <Tabs
      items={[
        { key: "live", label: <><EyeOutlined /> Tempo real</>, children: <LiveQueriesTab /> },
        { key: "cat", label: "Categorias", children: <CategoriesTab /> },
        { key: "manual", label: "Bloqueio manual", children: <ManualTab /> },
        { key: "allow", label: "Exceções", children: <AllowlistTab /> },
        { key: "sources", label: "Fontes", children: <SourcesTab /> },
        { key: "sched", label: "Agendamento", children: <ScheduleTab /> },
      ]}
    />
  </div>
);
