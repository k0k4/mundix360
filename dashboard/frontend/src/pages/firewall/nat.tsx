import { useCallback, useEffect, useState } from "react";
import {
  Tabs, Table, Button, Space, Tag, Modal, Form, Input, Select, Switch,
  Tooltip, Popconfirm, Alert, Typography, message as antdMessage,
} from "antd";
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  SwapOutlined, ExportOutlined, ImportOutlined, ThunderboltOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader } from "../../components/ui";
import { useInterfaces } from "../../hooks/useInterfaces";

const { Text } = Typography;

type PF = {
  id: string; enabled: boolean; iif: string; proto: "tcp" | "udp";
  dport: string; to_ip: string; to_port?: string; source: string;
  description: string;
};

/* ----------------------------------------------- forwarding banner ------- */
function ForwardingBanner({ onChange }: { onChange?: () => void }) {
  const [state, setState] = useState<any>(null);
  const [msg, ctx] = antdMessage.useMessage();
  const load = useCallback(async () => {
    const { data } = await api.get("/api/firewall/forwarding");
    setState(data);
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (v: boolean) => {
    try {
      await api.put("/api/firewall/forwarding", { enabled: v });
      msg.success(v ? "Encaminhamento IP ativado" : "Encaminhamento IP desativado");
      load();
      onChange?.();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha");
    }
  };
  if (!state) return null;
  return (
    <>
      {ctx}
      <Alert
        type={state.enabled ? "success" : "warning"}
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <Space>
            Encaminhamento de pacotes (IP forwarding):
            <b>{state.enabled ? "ATIVO" : "DESATIVADO"}</b>
            {!state.enabled && <Text type="secondary">
              — necessário para NAT/port-forward funcionar entre redes
            </Text>}
            {state.enabled && !state.persisted &&
              <Tag color="orange">não persistente</Tag>}
          </Space>
        }
        action={
          <Switch checked={state.enabled} onChange={toggle}
            checkedChildren="on" unCheckedChildren="off" />
        }
      />
    </>
  );
}

/* ----------------------------------------------- port forwards ----------- */
function PortForwardsTab() {
  const [rows, setRows] = useState<PF[]>([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<{ edit: boolean; row?: PF } | null>(null);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();
  const { ifaces, options: IFACES } = useInterfaces();
  const wanIface = ifaces.find((i) => i.is_wan || i.role === "wan")?.interface;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/firewall/port-forwards");
      setRows(data.port_forwards || []);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    const v = await form.validateFields();
    try {
      if (modal?.edit && modal.row) {
        await api.put(`/api/firewall/port-forwards/${modal.row.id}`, v);
      } else {
        await api.post("/api/firewall/port-forwards", v);
      }
      msg.success("Port-forward salvo e aplicado");
      setModal(null);
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao salvar");
    }
  };
  const remove = async (id: string) => {
    try {
      await api.delete(`/api/firewall/port-forwards/${id}`);
      msg.success("Removido");
      load();
    } catch (e: any) { msg.error(e?.response?.data?.detail || "Falha"); }
  };
  const toggle = async (r: PF) => {
    try {
      await api.put(`/api/firewall/port-forwards/${r.id}`, { ...r, enabled: !r.enabled });
      load();
    } catch (e: any) { msg.error(e?.response?.data?.detail || "Falha"); }
  };

  return (
    <div>
      {ctx}
      <ForwardingBanner />
      <div style={{ textAlign: "right", marginBottom: 12 }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} />
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              form.setFieldsValue({ iif: wanIface, proto: "tcp", source: "any", enabled: true });
              setModal({ edit: false });
            }}>
            Novo Port-Forward
          </Button>
        </Space>
      </div>
      <Table dataSource={rows} rowKey="id" loading={loading} size="middle"
        pagination={false}>
        <Table.Column title="On" width={60}
          render={(_, r: PF) => (
            <Switch size="small" checked={r.enabled} onChange={() => toggle(r)} />
          )} />
        <Table.Column title="WAN" dataIndex="iif" width={90}
          render={(i) => <span className="mx-mono">{i}</span>} />
        <Table.Column title="Externo" width={150}
          render={(_, r: PF) => (
            <span className="mx-mono">
              {r.proto}/{r.dport}
              {r.source && r.source !== "any" &&
                <Text type="secondary"> de {r.source}</Text>}
            </span>
          )} />
        <Table.Column title="" width={40} render={() => <SwapOutlined />} />
        <Table.Column title="Interno (destino)" width={170}
          render={(_, r: PF) => (
            <span className="mx-mono">
              {r.to_ip}:{r.to_port || r.dport}
            </span>
          )} />
        <Table.Column title="Descrição" dataIndex="description" />
        <Table.Column title="Ações" width={110}
          render={(_, r: PF) => (
            <Space>
              <Tooltip title="Editar">
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => { form.setFieldsValue(r); setModal({ edit: true, row: r }); }} />
              </Tooltip>
              <Popconfirm title="Remover este port-forward?" onConfirm={() => remove(r.id)}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          )} />
      </Table>

      <Modal
        title={`${modal?.edit ? "Editar" : "Novo"} port-forward (DNAT)`}
        open={!!modal} onOk={submit} onCancel={() => setModal(null)}
        okText="Salvar e aplicar" destroyOnClose width={560}
      >
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message="Redireciona conexões que chegam na interface WAN para um host interno. Portas de gestão (SSH/22) são bloqueadas por segurança." />
        <Form form={form} layout="vertical">
          <Space size="large" style={{ display: "flex" }}>
            <Form.Item name="iif" label="Interface WAN"
              rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={IFACES} showSearch optionFilterProp="label"
                placeholder="Interface de entrada" />
            </Form.Item>
            <Form.Item name="proto" label="Protocolo" initialValue="tcp"
              rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={[
                { value: "tcp", label: "TCP" },
                { value: "udp", label: "UDP" },
              ]} />
            </Form.Item>
            <Form.Item name="dport" label="Porta externa"
              rules={[{ required: true }]} style={{ flex: 1 }}>
              <Input placeholder="443" className="mx-mono" />
            </Form.Item>
          </Space>
          <Space size="large" style={{ display: "flex" }}>
            <Form.Item name="to_ip" label="IP interno de destino"
              rules={[{ required: true }]} style={{ flex: 2 }}>
              <Input placeholder="10.0.0.5" className="mx-mono" />
            </Form.Item>
            <Form.Item name="to_port" label="Porta interna (opcional)"
              style={{ flex: 1 }}>
              <Input placeholder="= externa" className="mx-mono" />
            </Form.Item>
          </Space>
          <Form.Item name="source" label="Origem permitida (opcional)"
            initialValue="any" tooltip="Restringe quem pode acessar. 'any' = qualquer origem. Aceita alias: ex. alias:web_servers.">
            <Input placeholder="any · alias:web_servers" className="mx-mono" />
          </Form.Item>
          <Form.Item name="description" label="Descrição">
            <Input placeholder="HTTPS público → servidor web DMZ" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

/* ----------------------------------------------- outbound NAT ------------ */
function OutboundTab() {
  const [data, setData] = useState<any>({ mode: "auto", rules: [] });
  const [loading, setLoading] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();
  const [modal, setModal] = useState(false);
  const [form] = Form.useForm();
  const { ifaces, options: IFACES } = useInterfaces();
  const wanIface = ifaces.find((i) => i.is_wan || i.role === "wan")?.interface;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/firewall/outbound");
      setData(data);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (next: any) => {
    try {
      await api.put("/api/firewall/outbound", next);
      msg.success("NAT de saída atualizado");
      load();
    } catch (e: any) { msg.error(e?.response?.data?.detail || "Falha"); }
  };

  const addRule = async () => {
    const v = await form.validateFields();
    const next = { mode: "manual",
      rules: [...(data.rules || []), { ...v, enabled: true }] };
    await save(next);
    setModal(false);
    form.resetFields();
  };
  const removeRule = async (idx: number) => {
    const rules = [...data.rules];
    rules.splice(idx, 1);
    await save({ mode: data.mode, rules });
  };

  return (
    <div>
      {ctx}
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message={<Space>
          NAT de saída (masquerade): as redes internas saem para a Internet com o
          IP da WAN. Modo atual: <Tag color={data.mode === "auto" ? "blue" : "purple"}>
            {data.mode}</Tag>
        </Space>} />
      <div style={{ textAlign: "right", marginBottom: 12 }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} />
          <Button icon={<PlusOutlined />} onClick={() => setModal(true)}>
            Regra manual
          </Button>
        </Space>
      </div>
      <Table dataSource={(data.rules || []).map((r: any, i: number) => ({ ...r, _i: i }))}
        rowKey={(r) => r.id || r._i} loading={loading} size="middle" pagination={false}>
        <Table.Column title="Rede de origem" dataIndex="source_net"
          render={(n) => <span className="mx-mono">{n}</span>} />
        <Table.Column title="Sai por" dataIndex="oif"
          render={(o) => <span className="mx-mono">{o}</span>} />
        <Table.Column title="Ação" render={() => <Tag color="geekblue">masquerade</Tag>} />
        <Table.Column title="Descrição" dataIndex="description" />
        <Table.Column title="" width={70}
          render={(_, r: any) => (
            <Popconfirm title="Remover regra de saída?" onConfirm={() => removeRule(r._i)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )} />
      </Table>

      <Modal title="Nova regra de NAT de saída" open={modal}
        onOk={addRule} onCancel={() => setModal(false)} okText="Adicionar" destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="source_net" label="Rede de origem (CIDR ou alias)"
            tooltip="CIDR (ex. 192.168.50.0/24) ou alias de rede/grupo (ex. alias:lan_nets)."
            rules={[{ required: true }]}>
            <Input placeholder="192.168.50.0/24 · alias:lan_nets" className="mx-mono" />
          </Form.Item>
          <Form.Item name="oif" label="Interface de saída" initialValue={wanIface}
            rules={[{ required: true }]}>
            <Select options={IFACES} showSearch optionFilterProp="label"
              placeholder="Interface de saída (WAN)" />
          </Form.Item>
          <Form.Item name="description" label="Descrição">
            <Input placeholder="NAT rede convidados" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export const NatPage = () => (
  <div>
    <PageHeader
      eyebrow={<><SwapOutlined /> Firewall · NAT</>}
      title="NAT"
      subtitle="Redirecionamento de portas (entrada) e masquerade (saída)"
    />
    <Tabs
      items={[
        {
          key: "pf", label: <span><ImportOutlined /> Port Forward (entrada)</span>,
          children: <PortForwardsTab />,
        },
        {
          key: "out", label: <span><ExportOutlined /> NAT de saída</span>,
          children: <OutboundTab />,
        },
      ]}
    />
  </div>
);
