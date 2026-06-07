import { useMemo, useState, useEffect, useCallback } from "react";
import { Drawer, Button, Tooltip, Badge, Space } from "antd";
import { RobotOutlined, CloseOutlined, PlusOutlined } from "@ant-design/icons";
import { useLocation } from "react-router-dom";
import { AssistantChat } from "./AssistantChat";

const CID_KEY = "mundix.ai.cid";

const ROUTE_LABELS: { match: (p: string) => boolean; label: string }[] = [
  { match: (p) => p === "/", label: "Visão Geral (dashboard)" },
  { match: (p) => p.startsWith("/assistant"), label: "Configuração do Mundix AI" },
  { match: (p) => p.startsWith("/siem"), label: "SIEM / Alertas" },
  { match: (p) => p.startsWith("/firewall/blocklist"), label: "Firewall — Bloqueio de IP" },
  { match: (p) => p.startsWith("/firewall/ports"), label: "Firewall — Regras de Porta" },
  { match: (p) => p.startsWith("/firewall/ruleset"), label: "Firewall — Ruleset (nft)" },
  { match: (p) => p.startsWith("/network/zones"), label: "Rede — VLANs / Zonas" },
  { match: (p) => p.startsWith("/network/reservations"), label: "Rede — Reservas DHCP" },
  { match: (p) => p.startsWith("/network/leases"), label: "Rede — Leases DHCP" },
  { match: (p) => p.startsWith("/content"), label: "Filtro de Conteúdo (DNS)" },
  { match: (p) => p.startsWith("/flows"), label: "Flows (NetFlow)" },
  { match: (p) => p.startsWith("/logs"), label: "Logs" },
  { match: (p) => p.startsWith("/system"), label: "Sistema / Serviços" },
];

function routeLabel(path: string): string {
  return ROUTE_LABELS.find((r) => r.match(path))?.label || path;
}

export function AssistantDock() {
  const [open, setOpen] = useState(false);
  const [cid, setCid] = useState<string | null>(
    () => localStorage.getItem(CID_KEY) || null,
  );
  const location = useLocation();

  // Persist the active conversation so closing/reopening (or a page reload)
  // resumes the same chat instead of silently starting a new one.
  const handleCid = useCallback((id: string) => {
    setCid(id);
    localStorage.setItem(CID_KEY, id);
  }, []);

  const newConversation = useCallback(() => {
    localStorage.removeItem(CID_KEY);
    setCid(null);
  }, []);

  const context = useMemo(
    () => `Tela atual do painel: ${routeLabel(location.pathname)} (${location.pathname})`,
    [location.pathname],
  );

  // Hide the dock on the dedicated AI config page (chat lives elsewhere there).
  if (location.pathname.startsWith("/assistant")) return null;

  return (
    <>
      {!open && (
        <Tooltip title="Mundix AI" placement="left">
          <Badge dot color="#22d3ee" offset={[-6, 6]}>
            <Button
              type="primary"
              shape="circle"
              size="large"
              icon={<RobotOutlined style={{ fontSize: 22 }} />}
              onClick={() => setOpen(true)}
              style={{
                position: "fixed",
                right: 24,
                bottom: 24,
                width: 56,
                height: 56,
                zIndex: 1000,
                boxShadow: "0 8px 24px rgba(34,211,238,0.35)",
              }}
            />
          </Badge>
        </Tooltip>
      )}

      <Drawer
        title={
          <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <RobotOutlined style={{ color: "#22d3ee" }} /> Mundix AI
            </span>
            <Tooltip title="Nova conversa">
              <Button
                type="text"
                size="small"
                icon={<PlusOutlined />}
                onClick={newConversation}
                style={{ color: "#9fb3d1" }}
              >
                Nova
              </Button>
            </Tooltip>
          </span>
        }
        placement="right"
        width={440}
        open={open}
        onClose={() => setOpen(false)}
        closeIcon={<CloseOutlined />}
        styles={{
          body: { padding: 0, background: "#0b1220" },
          header: { background: "#0e1830", borderBottom: "1px solid #1f3257" },
        }}
      >
        <div style={{ height: "100%" }}>
          <AssistantChat
            context={context}
            conversationId={cid}
            onConversationId={handleCid}
            emptyHint="Sou contextual à tela que você está vendo. Peça ações ou perguntas sobre esta área."
          />
        </div>
      </Drawer>
    </>
  );
}
