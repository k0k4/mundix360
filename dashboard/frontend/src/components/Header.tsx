import { useEffect, useState } from "react";
import { useCustom, useGetIdentity, useLogout } from "@refinedev/core";
import { Button, Tooltip, Dropdown, Avatar, Tag, Modal, Form, Input, message } from "antd";
import {
  AlignLeftOutlined,
  AlignRightOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  DownOutlined,
} from "@ant-design/icons";
import { api } from "../api";
import type { Identity } from "../authProvider";

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="mx-mono" style={{ color: "var(--mx-text-dim)" }}>
      {now.toLocaleTimeString("pt-BR")}
    </span>
  );
}

const ROLE_LABEL: Record<string, string> = {
  admin: "Administrador",
  operator: "Operador",
  viewer: "Somente leitura",
};

function UserMenu() {
  const { data: identity } = useGetIdentity<Identity>();
  const { mutate: logout } = useLogout();
  const [pwOpen, setPwOpen] = useState(false);
  const [form] = Form.useForm();

  if (!identity) return null;

  const changePassword = async (values: any) => {
    try {
      await api.post("/api/auth/change-password", {
        current_password: values.current_password,
        new_password: values.new_password,
      });
      message.success("Senha alterada");
      setPwOpen(false);
      form.resetFields();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || "Falha ao alterar a senha");
    }
  };

  const items = [
    {
      key: "who",
      disabled: true,
      label: (
        <div style={{ padding: "2px 0" }}>
          <div style={{ fontWeight: 600 }}>{identity.username}</div>
          <Tag style={{ marginTop: 4 }}>
            {ROLE_LABEL[identity.role] || identity.role}
          </Tag>
        </div>
      ),
    },
    { type: "divider" as const },
    {
      key: "password",
      icon: <KeyOutlined />,
      label: "Alterar senha",
      onClick: () => setPwOpen(true),
    },
    {
      key: "logout",
      icon: <LogoutOutlined />,
      danger: true,
      label: "Sair",
      onClick: () => logout(),
    },
  ];

  return (
    <>
      <Dropdown menu={{ items }} trigger={["click"]} placement="bottomRight">
        <Button type="text" style={{ color: "var(--mx-text)" }}>
          <Avatar size={22} icon={<UserOutlined />} style={{ marginRight: 6 }} />
          {identity.username}
          <DownOutlined style={{ fontSize: 10, marginLeft: 6 }} />
        </Button>
      </Dropdown>
      <Modal
        open={pwOpen}
        title="Alterar minha senha"
        okText="Salvar"
        cancelText="Cancelar"
        onCancel={() => setPwOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={changePassword}>
          <Form.Item
            name="current_password"
            label="Senha atual"
            rules={[{ required: true, message: "Informe a senha atual" }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="Nova senha"
            rules={[
              { required: true, message: "Informe a nova senha" },
              { min: 8, message: "Mínimo de 8 caracteres" },
            ]}
            hasFeedback
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="Confirmar nova senha"
            dependencies={["new_password"]}
            rules={[
              { required: true, message: "Confirme a nova senha" },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("new_password") === value)
                    return Promise.resolve();
                  return Promise.reject(new Error("As senhas não conferem"));
                },
              }),
            ]}
            hasFeedback
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export function Header({ onToggleSider }: { onToggleSider?: () => void }) {
  const { data } = useCustom<any>({ url: "/api/overview", method: "get" });
  const [siderPosition, setSiderPosition] = useState<"left" | "right">(() => {
    return (localStorage.getItem("mundix-sider-position") as "left" | "right") || "left";
  });

  const d = data?.data;
  const services = d?.services ?? [];
  const up = services.filter((s: any) => s.running).length;
  const total = services.length;
  const allUp = total > 0 && up === total;
  const state = total === 0 ? "warn" : allUp ? "" : up === 0 ? "down" : "warn";
  const label =
    total === 0
      ? "Conectando…"
      : allUp
      ? "Todos os serviços operacionais"
      : `${up}/${total} serviços ativos`;

  const handleToggleSider = () => {
    const newPosition = siderPosition === "left" ? "right" : "left";
    setSiderPosition(newPosition);
    localStorage.setItem("mundix-sider-position", newPosition);
    onToggleSider?.();
  };

  return (
    <header className="mx-header">
      <span className="mx-pill">
        <span className={`mx-dot ${state}`} />
        <span className="mx-pill-strong">{label}</span>
      </span>
      <span className="mx-spacer" />
      <Tooltip title={`Mover menu para ${siderPosition === "left" ? "direita" : "esquerda"}`}>
        <Button
          type="text"
          size="small"
          icon={siderPosition === "left" ? <AlignRightOutlined /> : <AlignLeftOutlined />}
          onClick={handleToggleSider}
          style={{ color: "var(--mx-text-dim)", marginRight: 8 }}
        />
      </Tooltip>
      <span className="mx-pill">
        <span className="mx-pill-strong">{d?.host?.hostname ?? "mundix"}</span>
      </span>
      <span className="mx-pill">
        <Clock />
      </span>
      <UserMenu />
    </header>
  );
}
