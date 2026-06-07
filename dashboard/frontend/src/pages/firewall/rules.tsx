import { useCallback, useEffect, useState } from "react";
import {
  Table, Button, Space, Tag, Modal, Form, Input, InputNumber, Select, Switch,
  Tooltip, Popconfirm, Segmented, Typography, AutoComplete, Divider,
  message as antdMessage,
} from "antd";
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined, FilterOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader } from "../../components/ui";
import { useInterfaces } from "../../hooks/useInterfaces";

const { Text } = Typography;

const ACTION_COLORS: Record<string, string> = {
  accept: "success", drop: "error", reject: "warning",
};

type Rule = {
  id: string; chain: "input" | "forward"; enabled: boolean;
  action: "accept" | "drop" | "reject"; iif?: string; oif?: string;
  proto: "tcp" | "udp" | "icmp" | "any"; source: string; dest: string;
  dport: string; log: boolean; log_rate?: string; rate_limit?: string;
  conn_limit?: number; description: string; order: number;
};

export const RulesPage = () => {
  const [rows, setRows] = useState<Rule[]>([]);
  const [aliases, setAliases] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [chain, setChain] = useState<"input" | "forward">("forward");
  const [modal, setModal] = useState<{ edit: boolean; row?: Rule } | null>(null);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();
  const { options: IFACES } = useInterfaces();
  const proto = Form.useWatch("proto", form);
  const logOn = Form.useWatch("log", form);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, a] = await Promise.all([
        api.get("/api/firewall/rules"),
        api.get("/api/firewall/aliases"),
      ]);
      setRows(r.data.rules || []);
      setAliases((a.data.aliases || []).map((x: any) => `alias:${x.name}`));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    const v = await form.validateFields();
    const payload = {
      ...v,
      chain: modal?.edit ? modal.row!.chain : chain,
      log_rate: (v.log_rate || "").trim(),
      rate_limit: (v.rate_limit || "").trim(),
      conn_limit: Number(v.conn_limit) > 0 ? Number(v.conn_limit) : 0,
    };
    try {
      if (modal?.edit && modal.row) {
        await api.put(`/api/firewall/rules/${modal.row.id}`, payload);
      } else {
        await api.post("/api/firewall/rules", payload);
      }
      msg.success("Regra salva e aplicada");
      setModal(null);
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao salvar");
    }
  };

  const toggle = async (r: Rule) => {
    try {
      await api.put(`/api/firewall/rules/${r.id}`, { ...r, enabled: !r.enabled });
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha");
    }
  };

  const move = async (r: Rule, dir: "up" | "down") => {
    try {
      await api.post(`/api/firewall/rules/${r.id}/move/${dir}`);
      load();
    } catch { /* noop */ }
  };

  const remove = async (id: string) => {
    try {
      await api.delete(`/api/firewall/rules/${id}`);
      msg.success("Regra removida");
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao remover");
    }
  };

  const filtered = rows.filter((r) => r.chain === chain);
  const addrOptions = ["any", ...aliases].map((v) => ({ value: v, label: v }));

  return (
    <div>
      {ctx}
      <PageHeader
        eyebrow={<><FilterOutlined /> Firewall · Regras</>}
        title="Regras de Filtro"
        subtitle="Controle de tráfego por interface, origem, destino, porta e ação — avaliadas de cima para baixo"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load} />
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => {
                form.resetFields();
                form.setFieldsValue({ action: "accept", proto: "any",
                  source: "any", dest: "any", enabled: true, log: false });
                setModal({ edit: false });
              }}>
              Nova Regra
            </Button>
          </Space>
        }
      />

      <Segmented
        value={chain}
        onChange={(v) => setChain(v as any)}
        options={[
          { label: "Forward (entre redes / Internet)", value: "forward" },
          { label: "Input (para o appliance)", value: "input" },
        ]}
        style={{ marginBottom: 16 }}
      />

      <Table dataSource={filtered} rowKey="id" loading={loading} size="middle"
        pagination={false}>
        <Table.Column title="#" width={70}
          render={(_, r: Rule, i) => (
            <Space size={2} direction="vertical">
              <Text type="secondary" style={{ fontSize: 12 }}>{i + 1}</Text>
              <Space size={0}>
                <Button type="text" size="small" icon={<ArrowUpOutlined />}
                  disabled={i === 0} onClick={() => move(r, "up")} />
                <Button type="text" size="small" icon={<ArrowDownOutlined />}
                  disabled={i === filtered.length - 1} onClick={() => move(r, "down")} />
              </Space>
            </Space>
          )} />
        <Table.Column title="On" width={60}
          render={(_, r: Rule) => (
            <Switch size="small" checked={r.enabled} onChange={() => toggle(r)} />
          )} />
        <Table.Column title="Ação" dataIndex="action" width={90}
          render={(a) => <Tag color={ACTION_COLORS[a]}>{a}</Tag>} />
        <Table.Column title="Origem" width={120}
          render={(_, r: Rule) => (
            <Space direction="vertical" size={0}>
              {r.iif && <span className="mx-mono">in: {r.iif}</span>}
              <span className="mx-mono">{r.source || "any"}</span>
            </Space>
          )} />
        <Table.Column title="Destino" width={140}
          render={(_, r: Rule) => (
            <Space direction="vertical" size={0}>
              {r.oif && r.chain === "forward" &&
                <span className="mx-mono">out: {r.oif}</span>}
              <span className="mx-mono">{r.dest || "any"}</span>
            </Space>
          )} />
        <Table.Column title="Proto/Porta" width={120}
          render={(_, r: Rule) => (
            <span className="mx-mono">
              {r.proto}{r.dport ? `:${r.dport}` : ""}
            </span>
          )} />
        <Table.Column title="Descrição" dataIndex="description"
          render={(d, r: Rule) => (
            <Space size={[4, 4]} wrap>
              {d}
              {r.log && (
                <Tag color="default">
                  log{r.log_rate ? ` ${r.log_rate}` : ""}
                </Tag>
              )}
              {r.rate_limit && <Tag color="blue">⏱ {r.rate_limit}</Tag>}
              {r.conn_limit ? <Tag color="volcano">⛓ {r.conn_limit} conn/ip</Tag> : null}
            </Space>
          )} />
        <Table.Column title="Ações" width={110}
          render={(_, r: Rule) => (
            <Space>
              <Tooltip title="Editar">
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => { form.setFieldsValue(r); setModal({ edit: true, row: r }); }} />
              </Tooltip>
              <Popconfirm title="Remover esta regra?" onConfirm={() => remove(r.id)}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          )} />
      </Table>

      <Modal
        title={`${modal?.edit ? "Editar" : "Nova"} regra · ${modal?.edit ? modal.row!.chain : chain}`}
        open={!!modal} onOk={submit} onCancel={() => setModal(null)}
        okText="Salvar e aplicar" destroyOnClose width={620}
      >
        <Form form={form} layout="vertical">
          <Space size="large" style={{ display: "flex" }}>
            <Form.Item name="action" label="Ação" initialValue="accept"
              style={{ flex: 1 }}>
              <Select options={[
                { value: "accept", label: "Aceitar" },
                { value: "drop", label: "Descartar (silencioso)" },
                { value: "reject", label: "Rejeitar (ICMP)" },
              ]} />
            </Form.Item>
            <Form.Item name="proto" label="Protocolo" initialValue="any"
              style={{ flex: 1 }}>
              <Select options={[
                { value: "any", label: "Qualquer" },
                { value: "tcp", label: "TCP" },
                { value: "udp", label: "UDP" },
                { value: "icmp", label: "ICMP" },
              ]} />
            </Form.Item>
          </Space>

          <Space size="large" style={{ display: "flex" }}>
            <Form.Item name="iif" label="Interface de entrada" style={{ flex: 1 }}>
              <Select allowClear showSearch optionFilterProp="label"
                placeholder="qualquer" options={IFACES} />
            </Form.Item>
            {(modal?.edit ? modal.row!.chain : chain) === "forward" && (
              <Form.Item name="oif" label="Interface de saída" style={{ flex: 1 }}>
                <Select allowClear showSearch optionFilterProp="label"
                  placeholder="qualquer" options={IFACES} />
              </Form.Item>
            )}
          </Space>

          <Space size="large" style={{ display: "flex" }}>
            <Form.Item name="source" label="Origem" initialValue="any"
              tooltip="any, um IP/CIDR ou alias:NOME" style={{ flex: 1 }}>
              <AutoComplete options={addrOptions} placeholder="any"
                className="mx-mono"
                filterOption={(i, o) =>
                  (o?.value as string).toLowerCase().includes(i.toLowerCase())} />
            </Form.Item>
            <Form.Item name="dest" label="Destino" initialValue="any"
              tooltip="any, um IP/CIDR ou alias:NOME" style={{ flex: 1 }}>
              <AutoComplete options={addrOptions} placeholder="any"
                className="mx-mono"
                filterOption={(i, o) =>
                  (o?.value as string).toLowerCase().includes(i.toLowerCase())} />
            </Form.Item>
          </Space>

          {(proto === "tcp" || proto === "udp") && (
            <Form.Item name="dport" label="Porta de destino"
              tooltip="ex: 443, 8000-8100 ou alias:NOME">
              <Input placeholder="443" className="mx-mono" />
            </Form.Item>
          )}

          <Form.Item name="description" label="Descrição">
            <Input placeholder="Permitir HTTPS LAN → DMZ" />
          </Form.Item>

          <Divider style={{ margin: "8px 0" }} orientation="left" plain>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Limites e registro (opcional)
            </Text>
          </Divider>

          <Space size="large" style={{ display: "flex" }}>
            <Form.Item name="rate_limit" label="Limite de taxa (por origem)"
              style={{ flex: 1 }}
              tooltip="Máx. de pacotes/conexões por IP de origem. Pacotes acima da taxa caem na política padrão. Ex: 25/second."
              rules={[{
                pattern: /^\s*$|^\d{1,7}\/(second|minute|hour|day)$/,
                message: "Use N/second|minute|hour|day",
              }]}>
              <Input placeholder="25/second" className="mx-mono" allowClear />
            </Form.Item>
            <Form.Item name="conn_limit" label="Conexões simultâneas (por origem)"
              style={{ flex: 1 }}
              tooltip="Máx. de conexões concorrentes por IP. Novas conexões acima do limite são descartadas. 0 = sem limite.">
              <InputNumber min={0} max={1000000} style={{ width: "100%" }}
                placeholder="0" className="mx-mono" />
            </Form.Item>
          </Space>

          <Space size="large">
            <Form.Item name="enabled" label="Ativa" valuePropName="checked"
              initialValue={true}>
              <Switch />
            </Form.Item>
            <Form.Item name="log" label="Registrar (log)" valuePropName="checked"
              initialValue={false}>
              <Switch />
            </Form.Item>
            {logOn && (
              <Form.Item name="log_rate" label="Taxa de log"
                tooltip="Limita a frequência das entradas de log. Vazio = 5/minute. '0' = registrar tudo (cuidado com volume)."
                rules={[{
                  pattern: /^\s*$|^0$|^\d{1,7}\/(second|minute|hour|day)$/,
                  message: "Use N/second|minute|hour|day ou 0",
                }]}>
                <Input placeholder="5/minute" className="mx-mono"
                  allowClear style={{ width: 160 }} />
              </Form.Item>
            )}
          </Space>
        </Form>
      </Modal>
    </div>
  );
};
