import { useEffect, useRef, useState, useCallback } from "react";
import {
  Layout,
  Input,
  Button,
  Typography,
  List,
  Avatar,
  Tag,
  Card,
  Space,
  Modal,
  Tooltip,
  Empty,
  Spin,
  message as antdMessage,
} from "antd";
import {
  RobotOutlined,
  UserOutlined,
  SendOutlined,
  PlusOutlined,
  DeleteOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  CodeOutlined,
  LockOutlined,
} from "@ant-design/icons";

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

const TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined;
const authHeaders = (): Record<string, string> =>
  TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

type ToolCard = {
  kind: "tool";
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  ok?: boolean;
};

type CodeChange = {
  kind: "code";
  id: string;
  path: string;
  description: string;
  exists: boolean;
  diff: string;
  added: number;
  resolved?: "applied" | "skipped";
};

type ChatItem =
  | { kind: "text"; role: "user" | "assistant"; content: string }
  | ToolCard
  | CodeChange;

type Conversation = { id: string; title: string; updated_at?: number };

function ToolBlock({ item }: { item: ToolCard }) {
  const ok = item.ok;
  return (
    <Card
      size="small"
      style={{ background: "#0e1830", borderColor: "#1f3257", marginBottom: 8 }}
      styles={{ body: { padding: "8px 12px" } }}
    >
      <Space direction="vertical" size={2} style={{ width: "100%" }}>
        <Space>
          <ToolOutlined style={{ color: "#1668dc" }} />
          <Text strong style={{ color: "#cbd5e1" }}>
            {item.name}
          </Text>
          {ok === true && (
            <Tag icon={<CheckCircleOutlined />} color="success">
              ok
            </Tag>
          )}
          {ok === false && (
            <Tag icon={<CloseCircleOutlined />} color="error">
              falha
            </Tag>
          )}
          {ok === undefined && <Spin size="small" />}
        </Space>
        {Object.keys(item.args || {}).length > 0 && (
          <Text code style={{ fontSize: 12, color: "#94a3b8" }}>
            {JSON.stringify(item.args)}
          </Text>
        )}
        {item.result !== undefined && (
          <pre
            style={{
              margin: 0,
              fontSize: 12,
              color: "#7dd3fc",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              maxHeight: 180,
              overflow: "auto",
            }}
          >
            {typeof item.result === "string"
              ? item.result
              : JSON.stringify(item.result, null, 2)}
          </pre>
        )}
      </Space>
    </Card>
  );
}

function CodeChangeBlock({
  item,
  onConfirm,
}: {
  item: CodeChange;
  onConfirm: (c: CodeChange) => void;
}) {
  return (
    <Card
      size="small"
      style={{
        background: "#1a1407",
        borderColor: "#7c5e10",
        marginBottom: 8,
      }}
      styles={{ body: { padding: "10px 12px" } }}
    >
      <Space direction="vertical" size={6} style={{ width: "100%" }}>
        <Space>
          <CodeOutlined style={{ color: "#e0a800" }} />
          <Text strong style={{ color: "#fde68a" }}>
            Alteração de código proposta
          </Text>
          <Tag color="gold">{item.exists ? "editar" : "criar"}</Tag>
        </Space>
        <Text code style={{ color: "#fde68a" }}>
          {item.path}
        </Text>
        <Text style={{ color: "#cbd5e1" }}>{item.description}</Text>
        <pre
          style={{
            margin: 0,
            fontSize: 12,
            background: "#0b1220",
            padding: 10,
            borderRadius: 6,
            maxHeight: 320,
            overflow: "auto",
            whiteSpace: "pre",
          }}
        >
          {(item.diff || "").split("\n").map((ln, i) => {
            let color = "#94a3b8";
            if (ln.startsWith("+") && !ln.startsWith("+++")) color = "#4ade80";
            else if (ln.startsWith("-") && !ln.startsWith("---"))
              color = "#f87171";
            else if (ln.startsWith("@@")) color = "#38bdf8";
            return (
              <div key={i} style={{ color }}>
                {ln || " "}
              </div>
            );
          })}
        </pre>
        {item.resolved ? (
          <Tag color={item.resolved === "applied" ? "success" : "default"}>
            {item.resolved === "applied"
              ? "Aplicada e commitada"
              : "Descartada"}
          </Tag>
        ) : (
          <Space>
            <Button
              type="primary"
              icon={<LockOutlined />}
              onClick={() => onConfirm(item)}
            >
              Aplicar (requer senha)
            </Button>
          </Space>
        )}
      </Space>
    </Card>
  );
}

export function AssistantPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [cid, setCid] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [pwModal, setPwModal] = useState<CodeChange | null>(null);
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const loadConversations = useCallback(async () => {
    const r = await fetch("/api/ai/conversations", { headers: authHeaders() });
    const j = await r.json();
    setConversations(j.conversations || []);
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [items]);

  const openConversation = useCallback(async (id: string) => {
    setCid(id);
    const r = await fetch(`/api/ai/conversations/${id}`, {
      headers: authHeaders(),
    });
    const j = await r.json();
    const msgs: ChatItem[] = (j.messages || [])
      .filter(
        (m: { role: string; content?: string }) =>
          (m.role === "user" || m.role === "assistant") && m.content,
      )
      .map((m: { role: "user" | "assistant"; content: string }) => ({
        kind: "text" as const,
        role: m.role,
        content: m.content,
      }));
    setItems(msgs);
  }, []);

  const newConversation = () => {
    setCid(null);
    setItems([]);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setItems((prev) => [
      ...prev,
      { kind: "text", role: "user", content: text },
    ]);
    setStreaming(true);

    let assistantBuf = "";
    const ensureAssistant = () => {
      setItems((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.kind === "text" && last.role === "assistant") {
          const copy = [...prev];
          copy[copy.length - 1] = {
            kind: "text",
            role: "assistant",
            content: assistantBuf,
          };
          return copy;
        }
        return [
          ...prev,
          { kind: "text", role: "assistant", content: assistantBuf },
        ];
      });
    };

    try {
      const resp = await fetch("/api/ai/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ conversation_id: cid, message: text }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const handleEvent = (event: string, dataStr: string) => {
        let data: any = {};
        try {
          data = JSON.parse(dataStr);
        } catch {
          /* ignore */
        }
        if (event === "meta" && data.conversation_id) {
          if (!cid) setCid(data.conversation_id);
        } else if (event === "token") {
          assistantBuf += data.text || "";
          ensureAssistant();
        } else if (event === "tool_started") {
          setItems((prev) => [
            ...prev,
            { kind: "tool", name: data.name, args: data.arguments || {} },
          ]);
          assistantBuf = "";
        } else if (event === "tool_result") {
          setItems((prev) => {
            const copy = [...prev];
            for (let i = copy.length - 1; i >= 0; i--) {
              const it = copy[i];
              if (it.kind === "tool" && it.name === data.name && it.result === undefined) {
                const res = data.result;
                copy[i] = {
                  ...it,
                  result: res,
                  ok:
                    res && typeof res === "object" && "ok" in res
                      ? Boolean((res as any).ok)
                      : res &&
                          typeof res === "object" &&
                          "returncode" in res
                        ? (res as any).returncode === 0
                        : true,
                };
                break;
              }
            }
            return copy;
          });
        } else if (event === "code_change_pending") {
          setItems((prev) => [
            ...prev,
            {
              kind: "code",
              id: data.id,
              path: data.path,
              description: data.description,
              exists: data.exists,
              diff: data.diff,
              added: data.added,
            },
          ]);
        } else if (event === "error") {
          antdMessage.error(data.message || "Erro no agente");
        }
      };

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const chunks = buffer.split("\n\n");
        buffer = done ? "" : chunks.pop() || "";
        for (const chunk of chunks) {
          const lines = chunk.split("\n");
          let ev = "message";
          const dataLines: string[] = [];
          for (const ln of lines) {
            if (ln.startsWith("event:")) ev = ln.slice(6).trim();
            else if (ln.startsWith("data:")) dataLines.push(ln.replace(/^data:\s?/, ""));
          }
          const dataStr = dataLines.join("\n").trim();
          if (dataStr) handleEvent(ev, dataStr);
        }
        if (done) break;
      }
    } catch (e: any) {
      antdMessage.error(e?.message || "Falha na conexão");
    } finally {
      setStreaming(false);
      loadConversations();
    }
  };

  const confirmCodeChange = async () => {
    if (!pwModal) return;
    setConfirming(true);
    try {
      const r = await fetch("/api/ai/code-change/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ change_id: pwModal.id, password }),
      });
      if (r.status === 403) {
        antdMessage.error("Senha incorreta.");
        return;
      }
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        antdMessage.error(j.detail || `Falha (HTTP ${r.status})`);
        return;
      }
      const j = await r.json();
      antdMessage.success(
        `Alteração aplicada${j.commit ? ` (${j.commit.slice(0, 8)})` : ""}.`,
      );
      setItems((prev) =>
        prev.map((it) =>
          it.kind === "code" && it.id === pwModal.id
            ? { ...it, resolved: "applied" }
            : it,
        ),
      );
      setPwModal(null);
      setPassword("");
    } catch (e: any) {
      antdMessage.error(e?.message || "Erro");
    } finally {
      setConfirming(false);
    }
  };

  const deleteConversation = async (id: string) => {
    await fetch(`/api/ai/conversations/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (id === cid) newConversation();
    loadConversations();
  };

  return (
    <Layout
      style={{
        height: "calc(100vh - 120px)",
        background: "transparent",
        gap: 12,
      }}
    >
      <Layout.Sider
        width={250}
        style={{
          background: "#0e1830",
          borderRadius: 10,
          padding: 12,
          overflow: "auto",
        }}
      >
        <Button
          block
          type="primary"
          icon={<PlusOutlined />}
          onClick={newConversation}
          style={{ marginBottom: 12 }}
        >
          Nova conversa
        </Button>
        <List
          dataSource={conversations}
          locale={{ emptyText: <Text type="secondary">Sem conversas</Text> }}
          renderItem={(c) => (
            <List.Item
              style={{
                cursor: "pointer",
                padding: "8px 10px",
                borderRadius: 8,
                background: c.id === cid ? "#1c2c4d" : "transparent",
                border: "none",
              }}
              onClick={() => openConversation(c.id)}
              actions={[
                <DeleteOutlined
                  key="del"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteConversation(c.id);
                  }}
                  style={{ color: "#64748b" }}
                />,
              ]}
            >
              <Text
                ellipsis
                style={{ color: "#cbd5e1", fontSize: 13, maxWidth: 150 }}
              >
                {c.title || "Conversa"}
              </Text>
            </List.Item>
          )}
        />
      </Layout.Sider>

      <Layout style={{ background: "#0b1220", borderRadius: 10 }}>
        <div
          ref={scrollRef}
          style={{ flex: 1, overflow: "auto", padding: 20 }}
        >
          {items.length === 0 ? (
            <div
              style={{
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Empty
                image={
                  <RobotOutlined
                    style={{ fontSize: 56, color: "#1668dc" }}
                  />
                }
                description={
                  <Space direction="vertical" size={4}>
                    <Text strong style={{ color: "#cbd5e1", fontSize: 16 }}>
                      Mundix AI
                    </Text>
                    <Text type="secondary">
                      Gestão por linguagem natural. Ex.: "Bloqueie o
                      xvideos.com", "Mostre os alertas críticos de hoje",
                      "Reinicie o suricata".
                    </Text>
                  </Space>
                }
              />
            </div>
          ) : (
            items.map((it, idx) => {
              if (it.kind === "tool")
                return <ToolBlock key={idx} item={it} />;
              if (it.kind === "code")
                return (
                  <CodeChangeBlock
                    key={idx}
                    item={it}
                    onConfirm={(c) => {
                      setPwModal(c);
                      setPassword("");
                    }}
                  />
                );
              const isUser = it.role === "user";
              return (
                <div
                  key={idx}
                  style={{
                    display: "flex",
                    gap: 10,
                    marginBottom: 14,
                    flexDirection: isUser ? "row-reverse" : "row",
                  }}
                >
                  <Avatar
                    icon={isUser ? <UserOutlined /> : <RobotOutlined />}
                    style={{
                      background: isUser ? "#334155" : "#1668dc",
                      flexShrink: 0,
                    }}
                  />
                  <div
                    style={{
                      maxWidth: "78%",
                      background: isUser ? "#1c2c4d" : "#111a2e",
                      border: "1px solid #1f3257",
                      borderRadius: 10,
                      padding: "8px 14px",
                    }}
                  >
                    <Paragraph
                      style={{
                        margin: 0,
                        color: "#e2e8f0",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {it.content || (streaming ? "…" : "")}
                    </Paragraph>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div
          style={{
            padding: 14,
            borderTop: "1px solid #1f3257",
            background: "#0e1830",
            borderRadius: "0 0 10px 10px",
          }}
        >
          <Space.Compact style={{ width: "100%" }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Peça algo ao Mundix AI…"
              autoSize={{ minRows: 1, maxRows: 5 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              disabled={streaming}
              style={{ background: "#0b1220" }}
            />
            <Tooltip title="Enviar (Enter)">
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={streaming}
                onClick={send}
                style={{ height: "auto" }}
              />
            </Tooltip>
          </Space.Compact>
        </div>
      </Layout>

      <Modal
        title={
          <Space>
            <LockOutlined /> Confirmar alteração de código
          </Space>
        }
        open={!!pwModal}
        onCancel={() => {
          setPwModal(null);
          setPassword("");
        }}
        onOk={confirmCodeChange}
        okText="Aplicar e commitar"
        confirmLoading={confirming}
        okButtonProps={{ disabled: !password }}
      >
        <Paragraph type="secondary">
          A alteração em <Text code>{pwModal?.path}</Text> será gravada no disco
          e commitada no git. Informe a senha mestra para autorizar.
        </Paragraph>
        <Input.Password
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Senha mestra"
          onPressEnter={confirmCodeChange}
          autoFocus
        />
      </Modal>
    </Layout>
  );
}
