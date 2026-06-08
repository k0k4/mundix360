import { useEffect, useRef, useState } from "react";
import { Button, Space, Typography, message as antdMessage } from "antd";
import {
  SafetyCertificateOutlined, CheckCircleOutlined,
} from "@ant-design/icons";
import { api } from "../api";

const { Text } = Typography;

type Pending = { pending: boolean; token?: string; seconds_left?: number; error?: boolean };

/**
 * Global confirm-or-revert banner. Polls the firewall "pending" state; whenever
 * a lockout-prone change was applied with auto-revert armed, it surfaces a
 * countdown and a Confirm button. If the operator loses connectivity (a rule
 * cut their own path), they simply cannot confirm and the firewall reverts
 * itself — mirroring `netplan try`.
 */
export function RevertBanner() {
  const [state, setState] = useState<Pending>({ pending: false });
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();
  const wasPending = useRef(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const res = await api.get<Pending>("/api/firewall/pending");
        if (!alive) return;
        setState(res.data);
        if (res.data.pending) {
          wasPending.current = true;
          setLeft(res.data.seconds_left ?? 0);
        } else if (wasPending.current) {
          wasPending.current = false;
          msg.warning("Alterações revertidas automaticamente (sem confirmação).");
        }
      } catch {
        /* network blip — keep last state */
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [msg]);

  // Local 1s countdown between polls.
  useEffect(() => {
    if (!state.pending) return;
    const id = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [state.pending]);

  const confirm = async () => {
    if (!state.token) return;
    setBusy(true);
    try {
      await api.post("/api/firewall/confirm", { token: state.token });
      wasPending.current = false;
      setState({ pending: false });
      msg.success("Conexão confirmada — alteração mantida.");
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao confirmar.");
    } finally {
      setBusy(false);
    }
  };

  if (!state.pending) return <>{ctx}</>;

  const isError = !!state.error;

  return (
    <>
      {ctx}
      <div
        style={{
          position: "fixed", left: "50%", bottom: 24, transform: "translateX(-50%)",
          zIndex: 2000,
          background: isError ? "#2a1215" : "#2b2111",
          border: `1px solid ${isError ? "#a61d24" : "#d89614"}`,
          borderRadius: 10, padding: "14px 20px", maxWidth: 680, width: "92%",
          boxShadow: "0 8px 28px rgba(0,0,0,0.5)",
        }}
      >
        <Space align="center" size={16} style={{ width: "100%", justifyContent: "space-between" }}>
          <Space size={12}>
            <SafetyCertificateOutlined
              style={{ color: isError ? "#ff4d4f" : "#faad14", fontSize: 22 }} />
            <Space direction="vertical" size={0}>
              <Text strong style={{ color: isError ? "#ff4d4f" : "#faad14" }}>
                {isError
                  ? "Falha ao reverter alteração de firewall"
                  : "Alteração de firewall aplicada com proteção"}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {isError
                  ? "O ruleset pode estar inconsistente — verifique o firewall."
                  : (<>Confirme que ainda tem conexão. Sem confirmação, reverte em{" "}
                      <Text strong style={{ color: "#faad14" }}>{left}s</Text>.</>)}
              </Text>
            </Space>
          </Space>
          <Space>
            <Button
              type="primary" danger={isError}
              icon={<CheckCircleOutlined />} loading={busy} onClick={confirm}
            >
              {isError ? "Dispensar" : `Confirmar (${left}s)`}
            </Button>
          </Space>
        </Space>
      </div>
    </>
  );
}
