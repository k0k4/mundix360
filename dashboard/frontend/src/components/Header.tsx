import { useEffect, useState } from "react";
import { useCustom } from "@refinedev/core";
import { Button, Tooltip } from "antd";
import { AlignLeftOutlined, AlignRightOutlined } from "@ant-design/icons";

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
    </header>
  );
}