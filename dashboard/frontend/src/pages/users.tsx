import { useEffect, useState } from "react";
import { useGetIdentity } from "@refinedev/core";
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Popconfirm,
  message,
  Typography,
} from "antd";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  KeyOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { api } from "../api";
import type { Identity } from "../authProvider";

const { Title, Text } = Typography;

type User = {
  id: string;
  username: string;
  role: "admin" | "operator" | "viewer";
  full_name: string;
  active: boolean;
  last_login: number | null;
};

const ROLE_LABEL: Record<string, { label: string; color: string }> = {
  admin: { label: "Administrador", color: "geekblue" },
  operator: { label: "Operador", color: "green" },
  viewer: { label: "Somente leitura", color: "default" },
};

function fmtTs(ts: number | null) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("pt-BR");
}

export function UsersPage() {
  const { data: identity } = useGetIdentity<Identity>();
  const [rows, setRows] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/auth/users");
      setRows(data.users);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || "Falha ao carregar usuários");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openCreate = () => {
    setCreating(true);
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ role: "operator", active: true });
  };

  const openEdit = (u: User) => {
    setEditing(u);
    setCreating(false);
    form.resetFields();
    form.setFieldsValue({
      role: u.role,
      active: u.active,
      full_name: u.full_name,
      password: "",
    });
  };

  const submit = async (values: any) => {
    try {
      if (creating) {
        await api.post("/api/auth/users", {
          username: values.username,
          password: values.password,
          role: values.role,
          full_name: values.full_name || "",
          active: values.active,
        });
        message.success("Usuário criado");
      } else if (editing) {
        const payload: any = {
          role: values.role,
          active: values.active,
          full_name: values.full_name || "",
        };
        if (values.password) payload.password = values.password;
        await api.patch(`/api/auth/users/${editing.id}`, payload);
        message.success("Usuário atualizado");
      }
      setCreating(false);
      setEditing(null);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || "Falha ao salvar");
    }
  };

  const remove = async (u: User) => {
    try {
      await api.delete(`/api/auth/users/${u.id}`);
      message.success("Usuário excluído");
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || "Falha ao excluir");
    }
  };

  const columns = [
    {
      title: "Usuário",
      dataIndex: "username",
      render: (v: string, r: User) => (
        <Space>
          <UserOutlined />
          <span style={{ fontWeight: 600 }}>{v}</span>
          {r.id === identity?.id && <Tag color="blue">você</Tag>}
        </Space>
      ),
    },
    { title: "Nome", dataIndex: "full_name", render: (v: string) => v || "—" },
    {
      title: "Perfil",
      dataIndex: "role",
      render: (v: string) => (
        <Tag color={ROLE_LABEL[v]?.color}>{ROLE_LABEL[v]?.label || v}</Tag>
      ),
    },
    {
      title: "Status",
      dataIndex: "active",
      render: (v: boolean) =>
        v ? <Tag color="success">Ativo</Tag> : <Tag>Inativo</Tag>,
    },
    { title: "Último acesso", dataIndex: "last_login", render: fmtTs },
    {
      title: "Ações",
      key: "actions",
      render: (_: any, r: User) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(r)}
          >
            Editar
          </Button>
          <Popconfirm
            title="Excluir este usuário?"
            okText="Excluir"
            okButtonProps={{ danger: true }}
            cancelText="Cancelar"
            disabled={r.id === identity?.id}
            onConfirm={() => remove(r)}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={r.id === identity?.id}
            >
              Excluir
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <Title level={5} style={{ margin: 0 }}>
            Usuários & Acesso
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Contas locais que acessam o painel. Perfis: administrador (tudo),
            operador (altera configuração), somente leitura.
          </Text>
        </Space>
      }
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Novo usuário
        </Button>
      }
    >
      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        columns={columns as any}
        pagination={false}
        size="middle"
      />

      <Modal
        open={creating || !!editing}
        title={creating ? "Novo usuário" : `Editar ${editing?.username || ""}`}
        okText="Salvar"
        cancelText="Cancelar"
        onCancel={() => {
          setCreating(false);
          setEditing(null);
        }}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          {creating && (
            <Form.Item
              name="username"
              label="Usuário"
              rules={[{ required: true, message: "Informe o usuário" }]}
            >
              <Input prefix={<UserOutlined />} placeholder="ex.: joao" />
            </Form.Item>
          )}
          <Form.Item name="full_name" label="Nome (opcional)">
            <Input placeholder="Nome completo" />
          </Form.Item>
          <Form.Item
            name="role"
            label="Perfil"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "admin", label: "Administrador" },
                { value: "operator", label: "Operador" },
                { value: "viewer", label: "Somente leitura" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="password"
            label={creating ? "Senha" : "Nova senha (deixe vazio para manter)"}
            rules={
              creating
                ? [
                    { required: true, message: "Informe a senha" },
                    { min: 8, message: "Mínimo de 8 caracteres" },
                  ]
                : [{ min: 8, message: "Mínimo de 8 caracteres" }]
            }
            hasFeedback
          >
            <Input.Password
              prefix={<KeyOutlined />}
              autoComplete="new-password"
              placeholder="••••••••"
            />
          </Form.Item>
          <Form.Item name="active" label="Ativo" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
