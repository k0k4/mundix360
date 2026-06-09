import { useMemo, useState, useEffect, useCallback } from "react";
import {
  Drawer,
  Button,
  Tooltip,
  Badge,
  Space,
  List,
  Input,
  Empty,
  Popconfirm,
  Typography,
  message as antdMessage,
} from "antd";
import {
  RobotOutlined,
  CloseOutlined,
  PlusOutlined,
  HistoryOutlined,
  DeleteOutlined,
  EditOutlined,
  CheckOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useLocation } from "react-router-dom";
import { AssistantChat, authHeaders } from "./AssistantChat";

const { Text } = Typography;
const CID_KEY = "mundix.ai.cid";

type Conversation = {
  id: string;
  title: string;
  updated_at: number;
  preview?: string;
};

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

function relTime(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "agora";
  if (s < 3600) return Math.floor(s / 60) + "min";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  return Math.floor(s / 86400) + "d";
}

export function AssistantDock() {
  const [open, setOpen] = useState(false);
  const [cid, setCid] = useState<string | null>(
    () => localStorage.getItem(CID_KEY) || null,
  );
  const [showList, setShowList] = useState(false);
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const location = useLocation();

  const handleCid = useCallback((id: string) => {
    setCid(id);
    localStorage.setItem(CID_KEY, id);
  }, []);

  const newConversation = useCallback(() => {
    localStorage.removeItem(CID_KEY);
    setCid(null);
    setShowList(false);
  }, []);

  const loadConvs = useCallback(async () => {
    try {
      const r = await fetch("/api/ai/conversations", { headers: authHeaders() });
      const j = await r.json();
      setConvs(j.conversations || []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (open && showList) loadConvs();
  }, [open, showList, loadConvs]);

  const selectConv = (id: string) => {
    handleCid(id);
    setShowList(false);
  };

  const renameConv = async (id: string) => {
    const title = editTitle.trim();
    if (!title) {
      setEditingId(null);
      return;
    }
    try {
      await fetch("/api/ai/conversations/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ title }),
      });
      setConvs((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    } catch {
      antdMessage.error("Falha ao renomear");
    } finally {
      setEditingId(null);
    }
  };

  const deleteConv = async (id: string) => {
    try {
      await fetch("/api/ai/conversations/" + id, {
        method: "DELETE",
        headers: authHeaders(),
      });
      setConvs((prev) => prev.filter((c) => c.id !== id));
      if (cid === id) newConversation();
    } catch {
      antdMessage.error("Falha ao excluir");
    }
  };

  const context = useMemo(
    () => "Tela atual do painel: " + routeLabel(location.pathname) + " (" + location.pathname + ")",
    [location.pathname],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return convs;
    return convs.filter(
      (c) =>
        (c.title || "").toLowerCase().includes(q) ||
        (c.preview || "").toLowerCase().includes(q),
    );
  }, [convs, search]);

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
            <Space size={2}>
              <Tooltip title="Conversas recentes">
                <Button
                  type="text"
                  size="small"
                  icon={<HistoryOutlined />}
                  onClick={() => setShowList((v) => !v)}
                  style={{ color: showList ? "#22d3ee" : "#9fb3d1" }}
                >
                  Recentes
                </Button>
              </Tooltip>
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
            </Space>
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
        <div style={{ height: "100%", position: "relative" }}>
          <AssistantChat
            context={context}
            conversationId={cid}
            onConversationId={handleCid}
            emptyHint="Sou contextual à tela que você está vendo. Peça ações ou perguntas sobre esta área."
          />

          {showList && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                background: "#0b1220",
                display: "flex",
                flexDirection: "column",
                zIndex: 5,
              }}
            >
              <div style={{ padding: 12, borderBottom: "1px solid #1f3257" }}>
                <Input
                  allowClear
                  prefix={<SearchOutlined style={{ color: "#64748b" }} />}
                  placeholder="Buscar conversas…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  style={{ background: "#0e1830" }}
                />
              </div>
              <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
                {filtered.length === 0 ? (
                  <Empty
                    style={{ marginTop: 40 }}
                    description={<Text type="secondary">Nenhuma conversa</Text>}
                  />
                ) : (
                  <List
                    dataSource={filtered}
                    renderItem={(c) => (
                      <List.Item
                        style={{
                          padding: "8px 10px",
                          borderRadius: 8,
                          cursor: "pointer",
                          background: c.id === cid ? "#13233f" : "transparent",
                          border:
                            c.id === cid ? "1px solid #1f3257" : "1px solid transparent",
                          marginBottom: 4,
                        }}
                        onClick={() => (editingId === c.id ? undefined : selectConv(c.id))}
                        actions={
                          editingId === c.id
                            ? [
                                <Button
                                  key="ok"
                                  type="text"
                                  size="small"
                                  icon={<CheckOutlined />}
                                  style={{ color: "#4ade80" }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    renameConv(c.id);
                                  }}
                                />,
                              ]
                            : [
                                <Tooltip key="edit" title="Renomear">
                                  <Button
                                    type="text"
                                    size="small"
                                    icon={<EditOutlined />}
                                    style={{ color: "#64748b" }}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEditingId(c.id);
                                      setEditTitle(c.title || "");
                                    }}
                                  />
                                </Tooltip>,
                                <Popconfirm
                                  key="del"
                                  title="Excluir conversa?"
                                  okText="Excluir"
                                  cancelText="Cancelar"
                                  onConfirm={(e) => {
                                    e?.stopPropagation();
                                    deleteConv(c.id);
                                  }}
                                  onCancel={(e) => e?.stopPropagation()}
                                >
                                  <Button
                                    type="text"
                                    size="small"
                                    icon={<DeleteOutlined />}
                                    style={{ color: "#64748b" }}
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                </Popconfirm>,
                              ]
                        }
                      >
                        <div style={{ width: "100%", minWidth: 0 }}>
                          {editingId === c.id ? (
                            <Input
                              size="small"
                              autoFocus
                              value={editTitle}
                              onChange={(e) => setEditTitle(e.target.value)}
                              onClick={(e) => e.stopPropagation()}
                              onPressEnter={() => renameConv(c.id)}
                              style={{ background: "#0e1830" }}
                            />
                          ) : (
                            <Space direction="vertical" size={0} style={{ width: "100%" }}>
                              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                                <Text strong ellipsis style={{ color: "#e2e8f0", maxWidth: 240 }}>
                                  {c.title || "Sem título"}
                                </Text>
                                <Text type="secondary" style={{ fontSize: 11 }}>
                                  {relTime(c.updated_at)}
                                </Text>
                              </Space>
                              {c.preview && (
                                <Text type="secondary" ellipsis style={{ fontSize: 12, maxWidth: 320 }}>
                                  {c.preview}
                                </Text>
                              )}
                            </Space>
                          )}
                        </div>
                      </List.Item>
                    )}
                  />
                )}
              </div>
            </div>
          )}
        </div>
      </Drawer>
    </>
  );
}
