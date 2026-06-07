import { useCallback, useEffect, useState } from "react";
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, Tooltip,
  Popconfirm, message as antdMessage,
} from "antd";
import {
  PlusOutlined, EditOutlined, DeleteOutlined, TagsOutlined, ReloadOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader } from "../../components/ui";

type Alias = {
  id: string; name: string; type: "host" | "network" | "port" | "group";
  values: string[]; description: string;
};

const TYPE_COLORS: Record<string, string> = {
  host: "cyan", network: "geekblue", port: "purple", group: "gold",
};

const TYPE_LABELS: Record<string, string> = {
  host: "Host (IPs)", network: "Rede (CIDR)", port: "Porta", group: "Grupo (aliases)",
};

export const AliasesPage = () => {
  const [rows, setRows] = useState<Alias[]>([]);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<{ edit: boolean; row?: Alias } | null>(null);
  const [form] = Form.useForm();
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/firewall/aliases");
      setRows(data.aliases || []);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    const v = await form.validateFields();
    try {
      if (modal?.edit && modal.row) {
        await api.put(`/api/firewall/aliases/${modal.row.id}`, v);
      } else {
        await api.post("/api/firewall/aliases", v);
      }
      msg.success("Alias salvo");
      setModal(null);
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao salvar");
    }
  };

  const remove = async (id: string) => {
    try {
      await api.delete(`/api/firewall/aliases/${id}`);
      msg.success("Alias removido");
      load();
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao remover");
    }
  };

  return (
    <div>
      {ctx}
      <PageHeader
        eyebrow={<><TagsOutlined /> Firewall · Aliases</>}
        title="Aliases"
        subtitle="Grupos nomeados de hosts, redes ou portas reutilizáveis nas regras"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load} />
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => { form.resetFields(); setModal({ edit: false }); }}>
              Novo Alias
            </Button>
          </Space>
        }
      />
      <Table dataSource={rows} rowKey="id" loading={loading} size="middle"
        pagination={false}>
        <Table.Column title="Nome" dataIndex="name"
          render={(n) => <span className="mx-mono"><b>{n}</b></span>} />
        <Table.Column title="Tipo" dataIndex="type" width={120}
          render={(t) => <Tag color={TYPE_COLORS[t]}>{TYPE_LABELS[t] || t}</Tag>} />
        <Table.Column title="Valores" dataIndex="values"
          render={(vs: string[], r: Alias) => (
            <Space size={[4, 4]} wrap>
              {vs.map((v) => (
                <Tag key={v} className="mx-mono"
                  color={r.type === "group" ? "gold" : undefined}>
                  {r.type === "group" ? `↳ ${v}` : v}
                </Tag>
              ))}
            </Space>
          )} />
        <Table.Column title="Descrição" dataIndex="description" />
        <Table.Column title="Ações" width={110}
          render={(_, r: Alias) => (
            <Space>
              <Tooltip title="Editar">
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => {
                    form.setFieldsValue(r);
                    setModal({ edit: true, row: r });
                  }} />
              </Tooltip>
              <Popconfirm title={`Remover ${r.name}?`} onConfirm={() => remove(r.id)}>
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          )} />
      </Table>

      <Modal
        title={modal?.edit ? "Editar alias" : "Novo alias"}
        open={!!modal} onOk={submit} onCancel={() => setModal(null)}
        okText="Salvar" destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="Nome"
            rules={[{ required: true },
              { pattern: /^[a-zA-Z][a-zA-Z0-9_]{1,30}$/, message: "letras/números/_" }]}>
            <Input placeholder="web_servers" className="mx-mono"
              disabled={modal?.edit} />
          </Form.Item>
          <Form.Item name="type" label="Tipo" initialValue="host"
            rules={[{ required: true }]}>
            <Select options={[
              { value: "host", label: "Host (IPs)" },
              { value: "network", label: "Rede (CIDR)" },
              { value: "port", label: "Porta" },
              { value: "group", label: "Grupo (aliases de endereço)" },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.type !== c.type}>
            {({ getFieldValue }) => {
              const type = getFieldValue("type");
              if (type === "group") {
                const opts = rows
                  .filter((a) =>
                    ["host", "network", "group"].includes(a.type) &&
                    a.name !== modal?.row?.name)
                  .map((a) => ({
                    value: a.name,
                    label: `${a.name} · ${TYPE_LABELS[a.type]}`,
                  }));
                return (
                  <Form.Item name="values" label="Aliases membros"
                    tooltip="Selecione aliases de host/rede/grupo. Grupos podem aninhar outros grupos (sem ciclos)."
                    rules={[{ required: true, message: "Selecione ao menos um alias" }]}>
                    <Select mode="multiple" placeholder="web1, db_net, dmz_group"
                      className="mx-mono" options={opts}
                      notFoundContent="Crie aliases de host/rede primeiro" />
                  </Form.Item>
                );
              }
              const ph = type === "port" ? "443, 8000-8100"
                : type === "network" ? "10.0.0.0/24, 192.168.1.0/24"
                : "10.0.0.5, 10.0.0.6";
              return (
                <Form.Item name="values" label="Valores"
                  tooltip="IPs, CIDRs ou portas. Enter para adicionar cada item."
                  rules={[{ required: true, message: "Informe ao menos um valor" }]}>
                  <Select mode="tags" tokenSeparators={[",", " "]}
                    placeholder={ph} className="mx-mono" />
                </Form.Item>
              );
            }}
          </Form.Item>
          <Form.Item name="description" label="Descrição">
            <Input placeholder="Servidores web da DMZ" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
