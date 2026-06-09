import { useEffect, useState } from "react";
import { useLogin } from "@refinedev/core";
import { useNavigate } from "react-router-dom";
import {
  Card,
  Form,
  Input,
  Button,
  Typography,
  Alert,
  Space,
  Spin,
} from "antd";
import {
  SafetyCertificateFilled,
  UserOutlined,
  LockOutlined,
} from "@ant-design/icons";
import { api } from "../api";

const { Title, Text } = Typography;

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background:
          "radial-gradient(1200px 600px at 50% -10%, #10203c 0%, #060b16 60%)",
        padding: 24,
      }}
    >
      <Card
        style={{ width: 400, maxWidth: "100%" }}
        styles={{ body: { padding: 28 } }}
      >
        <div style={{ textAlign: "center", marginBottom: 18 }}>
          <span style={{ fontSize: 40, color: "#2f81f7" }}>
            <SafetyCertificateFilled />
          </span>
          <Title level={4} style={{ margin: "8px 0 0" }}>
            MUNDIX <span style={{ color: "#2f81f7" }}>360</span>
          </Title>
        </div>
        {children}
      </Card>
    </div>
  );
}

export function LoginPage() {
  const { mutate: login, isLoading } = useLogin();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // If the appliance has no admin yet, send the operator to first-run setup.
    api
      .get("/api/auth/state")
      .then(({ data }) => {
        if (!data.initialized) navigate("/setup", { replace: true });
      })
      .finally(() => setChecking(false));
  }, [navigate]);

  if (checking)
    return (
      <Shell>
        <div style={{ textAlign: "center" }}>
          <Spin />
        </div>
      </Shell>
    );

  return (
    <Shell>
      <Text type="secondary">Acesse o painel de gestão de segurança.</Text>
      <Form
        layout="vertical"
        style={{ marginTop: 16 }}
        onFinish={(values) =>
          login(values, {
            onError: (e: any) =>
              setError(e?.message || "Falha na autenticação"),
          })
        }
      >
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            style={{ marginBottom: 12 }}
          />
        )}
        <Form.Item
          name="username"
          label="Usuário"
          rules={[{ required: true, message: "Informe o usuário" }]}
        >
          <Input
            prefix={<UserOutlined />}
            placeholder="admin"
            autoComplete="username"
            size="large"
          />
        </Form.Item>
        <Form.Item
          name="password"
          label="Senha"
          rules={[{ required: true, message: "Informe a senha" }]}
        >
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="••••••••"
            autoComplete="current-password"
            size="large"
          />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          block
          size="large"
          loading={isLoading}
        >
          Entrar
        </Button>
      </Form>
    </Shell>
  );
}

export function SetupPage() {
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get("/api/auth/state")
      .then(({ data }) => {
        if (data.initialized) navigate("/login", { replace: true });
      })
      .finally(() => setChecking(false));
  }, [navigate]);

  if (checking)
    return (
      <Shell>
        <div style={{ textAlign: "center" }}>
          <Spin />
        </div>
      </Shell>
    );

  const onFinish = async (values: any) => {
    setError(null);
    setSubmitting(true);
    try {
      await api.post("/api/auth/setup", {
        username: values.username,
        password: values.password,
        full_name: values.full_name || "",
      });
      // Setup logs the new admin straight in (cookie set) — go to the dashboard.
      window.location.assign("/");
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Não foi possível concluir a configuração");
      setSubmitting(false);
    }
  };

  return (
    <Shell>
      <Space direction="vertical" size={4} style={{ marginBottom: 8 }}>
        <Title level={5} style={{ margin: 0 }}>
          Configuração inicial
        </Title>
        <Text type="secondary">
          Crie a primeira conta de administrador para proteger o appliance.
        </Text>
      </Space>
      <Form layout="vertical" style={{ marginTop: 16 }} onFinish={onFinish}>
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            style={{ marginBottom: 12 }}
          />
        )}
        <Form.Item name="full_name" label="Nome (opcional)">
          <Input placeholder="Administrador" size="large" />
        </Form.Item>
        <Form.Item
          name="username"
          label="Usuário"
          rules={[{ required: true, message: "Informe o usuário" }]}
        >
          <Input prefix={<UserOutlined />} placeholder="admin" size="large" />
        </Form.Item>
        <Form.Item
          name="password"
          label="Senha"
          rules={[
            { required: true, message: "Informe a senha" },
            { min: 8, message: "Mínimo de 8 caracteres" },
          ]}
          hasFeedback
        >
          <Input.Password
            prefix={<LockOutlined />}
            placeholder="Senha forte"
            autoComplete="new-password"
            size="large"
          />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="Confirmar senha"
          dependencies={["password"]}
          rules={[
            { required: true, message: "Confirme a senha" },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue("password") === value)
                  return Promise.resolve();
                return Promise.reject(new Error("As senhas não conferem"));
              },
            }),
          ]}
          hasFeedback
        >
          <Input.Password
            prefix={<LockOutlined />}
            autoComplete="new-password"
            size="large"
          />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          block
          size="large"
          loading={submitting}
        >
          Criar administrador
        </Button>
      </Form>
    </Shell>
  );
}
